"""
Hybrid retrieval service — two-pass pipeline:
  Pass 1: file_metadata_summary_search — lightweight file-level scan (title, keywords, tags)
  Pass 2: vector_search + metadata_search + graph_search on selected files
  Pass 3: get_file_graph_neighbors — one-hop graph traversal
"""
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from sqlalchemy import or_, select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    ChunkEmbedding, File, FileChunk, FileEntity,
    GraphEdge, GraphNode, WorkspaceMember,
)
from app.schemas import SourceCitation


# ─── Level-based access control ─────────────────────────────────────────────

async def get_accessible_file_ids(
    db: AsyncSession,
    user_id: UUID,
    workspace_id: UUID,
    my_level: int,
    my_role_id: Optional[UUID] = None,
) -> List[UUID]:
    """
    Returns file IDs the user can access — restricted to processing_status='done'.
    Used by AI retrieval (vector/graph search) so only fully-processed chunks are returned.

    Governance model:
      1. Level 1 (Top Member / Admin) sees everything.
      2. For normal users (level > 1):
         - Clearance check: min_access_level IS NULL OR min_access_level >= :user_level
         - ACL / Group check:
           If file.is_inherited = False: allowed_role_ids is empty or my_role_id in allowed_role_ids
           If file.is_inherited = True: folder IS NULL or folder check passes
    """
    if my_level == 1:
        result = await db.execute(
            text("""
                SELECT file_id FROM files
                WHERE workspace_id = :wid
                  AND status NOT IN ('archived')
                  AND processing_status = 'done'
            """),
            {"wid": str(workspace_id)},
        )
        return [row[0] for row in result.fetchall()]

    result = await db.execute(
        text("""
            SELECT f.file_id FROM files f
            LEFT JOIN workspace_folders fold ON f.folder_id = fold.folder_id
            WHERE f.workspace_id = :wid
              AND f.status NOT IN ('archived')
              AND f.processing_status = 'done'
              AND (f.min_access_level IS NULL OR f.min_access_level >= :user_level)
              AND (
                  (
                      f.is_inherited = false
                      AND (f.allowed_role_ids = '{}' OR f.allowed_role_ids IS NULL OR :role_id = ANY(f.allowed_role_ids))
                  )
                  OR (
                      f.is_inherited = true
                      AND (
                          f.folder_id IS NULL
                          OR (
                              (fold.min_access_level IS NULL OR fold.min_access_level >= :user_level)
                              AND (fold.allowed_role_ids = '{}' OR fold.allowed_role_ids IS NULL OR :role_id = ANY(fold.allowed_role_ids))
                          )
                      )
                  )
              )
        """),
        {
            "wid": str(workspace_id),
            "user_level": my_level,
            "role_id": str(my_role_id) if my_role_id else None,
        },
    )
    return [row[0] for row in result.fetchall()]


async def get_accessible_file_ids_any_status(
    db: AsyncSession,
    user_id: UUID,
    workspace_id: UUID,
    my_level: int,
    my_role_id: Optional[UUID] = None,
) -> List[UUID]:
    """
    Returns file IDs the user can access — regardless of processing_status.
    Used by the document list endpoint so newly uploaded files (pending/processing)
    appear immediately in the workspace Documents window.
    """
    if my_level == 1:
        result = await db.execute(
            text("""
                SELECT file_id FROM files
                WHERE workspace_id = :wid
                  AND status NOT IN ('archived')
            """),
            {"wid": str(workspace_id)},
        )
        return [row[0] for row in result.fetchall()]

    result = await db.execute(
        text("""
            SELECT f.file_id FROM files f
            LEFT JOIN workspace_folders fold ON f.folder_id = fold.folder_id
            WHERE f.workspace_id = :wid
              AND f.status NOT IN ('archived')
              AND (f.min_access_level IS NULL OR f.min_access_level >= :user_level)
              AND (
                  (
                      f.is_inherited = false
                      AND (f.allowed_role_ids = '{}' OR f.allowed_role_ids IS NULL OR :role_id = ANY(f.allowed_role_ids))
                  )
                  OR (
                      f.is_inherited = true
                      AND (
                          f.folder_id IS NULL
                          OR (
                              (fold.min_access_level IS NULL OR fold.min_access_level >= :user_level)
                              AND (fold.allowed_role_ids = '{}' OR fold.allowed_role_ids IS NULL OR :role_id = ANY(fold.allowed_role_ids))
                          )
                      )
                  )
              )
        """),
        {
            "wid": str(workspace_id),
            "user_level": my_level,
            "role_id": str(my_role_id) if my_role_id else None,
        },
    )
    return [row[0] for row in result.fetchall()]


# ─── Pass 1: Lightweight file-level metadata scan ────────────────────────────

async def file_metadata_summary_search(
    db: AsyncSession,
    query: str,
    accessible_ids: List[UUID],
) -> List[Dict[str, Any]]:
    """
    PASS 1 — Fast scan of file-level metadata only (no chunk reads, no embeddings).
    Returns compact file summary dicts that the LLM can use to select relevant files.

    Matches against: title, original_name, description, keywords[], tags[]
    Returns ALL accessible files so LLM has full picture (bounded by accessible_ids).
    """
    if not accessible_ids:
        return []

    result = await db.execute(
        text("""
            SELECT
                f.file_id,
                f.title,
                f.original_name,
                f.description,
                f.keywords,
                f.tags,
                f.file_family,
                f.upload_ts,
                f.version_number
            FROM files f
            WHERE CAST(f.file_id AS text) = ANY(:ids)
            ORDER BY f.upload_ts DESC
            LIMIT 50
        """),
        {"ids": [str(i) for i in accessible_ids]},
    )
    rows = result.fetchall()
    return [
        {
            "file_id": str(r[0]),
            "title": r[1] or r[2],
            "original_name": r[2],
            "description": r[3] or "",
            "keywords": r[4] or [],
            "tags": r[5] or [],
            "file_family": r[6],
            "upload_ts": r[7].isoformat() if r[7] else "",
            "version_number": r[8],
        }
        for r in rows
    ]


# ─── Pass 1b / 2: Chunk-level Metadata Keyword Search ────────────────────────

async def metadata_search(
    db: AsyncSession,
    query: str,
    accessible_ids: List[UUID],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Keyword search against title, original_name, tags, description and content — chunk-level."""
    if not accessible_ids:
        return []

    terms = [t.strip() for t in query.lower().split() if len(t.strip()) > 2]
    if not terms:
        return []

    result = await db.execute(
        text("""
            SELECT f.file_id, fc.chunk_id, fc.content, fc.chunk_type, fc.page_number,
                   f.title, f.original_name, f.version_number, f.file_family,
                   0.7::float AS score
            FROM files f
            JOIN file_chunks fc ON fc.file_id = f.file_id
            WHERE CAST(f.file_id AS text) = ANY(:ids)
              AND (
                  f.title ILIKE :q
                  OR f.original_name ILIKE :q
                  OR f.description ILIKE :q
                  OR fc.content ILIKE :q
              )
            ORDER BY f.upload_ts DESC
            LIMIT :lim
        """),
        {
            "ids": [str(i) for i in accessible_ids],
            "q": f"%{terms[0]}%",
            "lim": limit,
        },
    )
    rows = result.fetchall()
    return [_row_to_chunk_dict(r, source="metadata") for r in rows]


# ─── Pass 2: Vector Search ────────────────────────────────────────────────────

async def vector_search(
    db: AsyncSession,
    query: str,
    accessible_ids: List[UUID],
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    Cosine similarity search using pgvector.
    Returns top_k chunks with similarity >= SIMILARITY_THRESHOLD.
    accessible_ids should already be pre-filtered to selected files from Pass 1.
    """
    if not accessible_ids or not settings.GEMINI_API_KEY:
        return []

    embedding = await _embed_text(query)
    if not embedding:
        return []

    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    result = await db.execute(
        text("""
            SELECT f.file_id, fc.chunk_id, fc.content, fc.chunk_type, fc.page_number,
                   f.title, f.original_name, f.version_number, f.file_family,
                   1 - (ce.embedding <=> CAST(:emb AS vector)) AS score
            FROM chunk_embeddings ce
            JOIN file_chunks fc ON fc.chunk_id = ce.chunk_id
            JOIN files f ON f.file_id = fc.file_id
            WHERE CAST(f.file_id AS text) = ANY(:ids)
              AND 1 - (ce.embedding <=> CAST(:emb AS vector)) > :threshold
            ORDER BY score DESC
            LIMIT :top_k
        """),
        {
            "emb": embedding_str,
            "ids": [str(i) for i in accessible_ids],
            "threshold": settings.SIMILARITY_THRESHOLD,
            "top_k": top_k,
        },
    )
    rows = result.fetchall()
    return [_row_to_chunk_dict(r, source="vector") for r in rows]


# ─── Pass 2b: Graph Search (Shadow Overlay Graph Search) ─────────────────────

async def graph_search(
    db: AsyncSession,
    query: str,
    accessible_ids: List[UUID],
    workspace_id: Optional[UUID] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Shadow Overlay Graph Search (Feature 1):
    Performs a UNION query:
      1. Fetch edges (BELONGS_TO_ASSET, SIMILAR_TO, RELATED_TO, SUPERSEDED_BY) from base graph_edges.
      2. Subtract edges marked DELETE in user_graph_mutations for this workspace.
      3. Append edges marked ADD in user_graph_mutations, applying user-defined weight boost.
    """
    if not accessible_ids:
        return []

    # Match common industrial equipment tag patterns or query keywords
    patterns = [
        r'\b[A-Z]{1,3}-?\d{3,6}[A-Z]?\b',  # P-204, V-1042A, TIC-301
        r'\b[A-Z]{2,4}\d{3,6}\b',            # TK001, HX204
    ]
    entity_matches = []
    for pat in patterns:
        entity_matches.extend(re.findall(pat, query.upper()))

    # Also add words > 3 characters from query as potential labels/entities
    words = [w.upper() for w in query.split() if len(w) > 3]
    entity_matches.extend(words)
    entity_matches = list(set(entity_matches))

    if not entity_matches:
        return []

    workspace_id_str = str(workspace_id) if workspace_id else "00000000-0000-0000-0000-000000000000"

    result = await db.execute(
        text("""
            -- Part A: Base graph edges (BELONGS_TO_ASSET, RELATED_TO, SIMILAR_TO, SUPERSEDED_BY), excluding shadow-deleted ones
            SELECT DISTINCT
                f.file_id,
                CAST(NULL AS uuid) AS chunk_id,
                f.title AS content,
                'file' AS chunk_type,
                NULL::int AS page_number,
                f.title,
                f.original_name,
                f.version_number,
                f.file_family,
                0.65::float AS score
            FROM graph_nodes gn_node
            JOIN graph_edges ge ON (ge.to_node_id = gn_node.node_id OR ge.from_node_id = gn_node.node_id)
            JOIN graph_nodes gn_file ON gn_file.node_id = CASE
                WHEN ge.from_node_id = gn_node.node_id THEN ge.to_node_id
                ELSE ge.from_node_id
            END AND gn_file.node_type = 'file'
            JOIN files f ON f.file_id::text = gn_file.external_id
            WHERE gn_node.label = ANY(:entities)
              AND CAST(f.file_id AS text) = ANY(:ids)
              AND NOT EXISTS (
                  SELECT 1 FROM user_graph_mutations ugm
                  WHERE ugm.workspace_id = CAST(:wid AS uuid)
                    AND ugm.action = 'DELETE'
                    AND ugm.from_node_id = ge.from_node_id
                    AND ugm.to_node_id = ge.to_node_id
              )

            UNION

            -- Part B: User-added shadow edges (ADD mutations), scoring boosted by custom weight
            SELECT DISTINCT
                f.file_id,
                CAST(NULL AS uuid) AS chunk_id,
                f.title AS content,
                'file' AS chunk_type,
                NULL::int AS page_number,
                f.title,
                f.original_name,
                f.version_number,
                f.file_family,
                (0.65 * ugm.weight)::float AS score
            FROM user_graph_mutations ugm
            JOIN graph_nodes gn_from ON gn_from.node_id = ugm.from_node_id AND gn_from.node_type = 'file'
            JOIN graph_nodes gn_to   ON gn_to.node_id   = ugm.to_node_id
            JOIN files f ON f.file_id::text = gn_from.external_id
            WHERE ugm.workspace_id = CAST(:wid AS uuid)
              AND ugm.action = 'ADD'
              AND gn_to.label = ANY(:entities)
              AND CAST(f.file_id AS text) = ANY(:ids)

            LIMIT :lim
        """),
        {
            "entities": entity_matches,
            "ids": [str(i) for i in accessible_ids],
            "wid": workspace_id_str,
            "lim": limit,
        },
    )
    rows = result.fetchall()
    return [_row_to_chunk_dict(r, source="graph") for r in rows]


# ─── Pass 3: Graph Neighbors (one-hop, file→file & shadow overlay) ───────────

async def get_file_graph_neighbors(
    db: AsyncSession,
    file_ids: List[UUID],
    accessible_ids: List[UUID],
    limit: int = 10,
) -> List[UUID]:
    """
    PASS 3 — Traverse graph edges one hop from the selected files.
    Returns file UUIDs of connected files.
    Includes base graph_edges and user-added shadow mutations (ADD action).
    """
    if not file_ids:
        return []

    result = await db.execute(
        text("""
            -- Base edges: both directions from selected file nodes
            SELECT DISTINCT target_file.file_id
            FROM graph_nodes gn_src
            JOIN graph_edges ge ON (
                ge.from_node_id = gn_src.node_id OR ge.to_node_id = gn_src.node_id
            )
            JOIN graph_nodes gn_target ON (
                gn_target.node_id = CASE
                    WHEN ge.from_node_id = gn_src.node_id THEN ge.to_node_id
                    ELSE ge.from_node_id
                END
            )
            JOIN files target_file ON target_file.file_id::text = gn_target.external_id
            WHERE gn_src.external_id = ANY(:src_ids)
              AND gn_src.node_type = 'file'
              AND gn_target.node_type = 'file'
              AND CAST(target_file.file_id AS text) = ANY(:acc_ids)
              AND CAST(target_file.file_id AS text) != ALL(:src_ids)

            UNION

            -- User-added shadow edges (ADD mutations)
            SELECT DISTINCT target_file.file_id
            FROM user_graph_mutations ugm
            JOIN graph_nodes gn_src ON gn_src.node_id = ugm.from_node_id AND gn_src.node_type = 'file'
            JOIN graph_nodes gn_target ON gn_target.node_id = ugm.to_node_id AND gn_target.node_type = 'file'
            JOIN files target_file ON target_file.file_id::text = gn_target.external_id
            WHERE ugm.action = 'ADD'
              AND gn_src.external_id = ANY(:src_ids)
              AND CAST(target_file.file_id AS text) = ANY(:acc_ids)
              AND CAST(target_file.file_id AS text) != ALL(:src_ids)

            LIMIT :lim
        """),
        {
            "src_ids": [str(i) for i in file_ids],
            "acc_ids": [str(i) for i in accessible_ids],
            "lim": limit,
        },
    )
    return [row[0] for row in result.fetchall()]


# ─── Fusion ───────────────────────────────────────────────────────────────────

def fuse_results(
    meta: List[Dict],
    vec: List[Dict],
    graph: List[Dict],
    top_k: int = 8,
) -> List[Dict]:
    """Merge and rank results from all retrieval sources (Metadata, Vector, Graph)."""
    seen = {}
    weights = {"metadata": 0.35, "vector": 0.45, "graph": 0.20, "fallback": 0.30}

    for item in meta + vec + graph:
        key = item["chunk_id"] or item["file_id"]
        w = weights.get(item["source"], 0.33)
        if key not in seen:
            seen[key] = {**item, "fused_score": item["score"] * w}
        else:
            seen[key]["fused_score"] += item["score"] * w

    ranked = sorted(seen.values(), key=lambda x: x["fused_score"], reverse=True)
    return ranked[:top_k]


# ─── Similarity Expansion ─────────────────────────────────────────────────────

async def similarity_expand(
    db: AsyncSession,
    anchor_file_ids: List[UUID],
    accessible_ids: List[UUID],
    limit: int = 5,
) -> List[UUID]:
    """Find files related to the anchor files via graph edges."""
    if not anchor_file_ids:
        return []

    result = await db.execute(
        text("""
            SELECT DISTINCT f.file_id
            FROM graph_nodes gn_anchor
            JOIN graph_edges ge ON ge.from_node_id = gn_anchor.node_id
                AND ge.edge_type IN ('SIMILAR_TO', 'BELONGS_TO_ASSET', 'REFERENCES', 'LINKED_PROCEDURE', 'SUPERSEDED_BY', 'RELATED_TO')
            JOIN graph_nodes gn_target ON gn_target.node_id = ge.to_node_id
            JOIN files f ON f.file_id::text = gn_target.external_id
            WHERE gn_anchor.external_id = ANY(:anchor_ids)
              AND CAST(f.file_id AS text) = ANY(:acc_ids)
              AND CAST(f.file_id AS text) != ALL(:anchor_ids)
            LIMIT :lim
        """),
        {
            "anchor_ids": [str(i) for i in anchor_file_ids],
            "acc_ids": [str(i) for i in accessible_ids],
            "lim": limit,
        },
    )
    return [row[0] for row in result.fetchall()]


# ─── Context Assembly ─────────────────────────────────────────────────────────

async def assemble_context(
    db: AsyncSession,
    fused_chunks: List[Dict],
) -> Tuple[str, List[SourceCitation]]:
    """Build the LLM context string and citation list from fused chunks."""
    context_parts = []
    citations = []
    seen_file_ids = set()
    total_tokens = 0

    for chunk in fused_chunks:
        chunk_text = chunk.get("content", "")
        if not chunk_text:
            continue

        chunk_tokens = len(chunk_text) // 4
        if total_tokens + chunk_tokens > settings.MAX_CONTEXT_TOKENS:
            break

        source_label = f"[Source: {chunk.get('original_name', 'Unknown')} v{chunk.get('version_number', '?')}"
        if chunk.get("page_number"):
            source_label += f" p.{chunk['page_number']}"
        source_label += f" | File ID: {chunk['file_id']}]"

        context_parts.append(f"{source_label}\n{chunk_text}")
        total_tokens += chunk_tokens

        fid = UUID(str(chunk["file_id"]))
        if fid not in seen_file_ids:
            seen_file_ids.add(fid)
            citations.append(SourceCitation(
                file_id=fid,
                title=chunk.get("title"),
                original_name=chunk.get("original_name", ""),
                version_number=chunk.get("version_number", 1),
                file_family=chunk.get("file_family", ""),
                chunk_type=chunk.get("chunk_type"),
                page_number=chunk.get("page_number"),
                relevance_score=round(chunk.get("fused_score", chunk.get("score", 0.0)), 3),
            ))

    return "\n\n---\n\n".join(context_parts), citations


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_chunk_dict(row, source: str) -> Dict[str, Any]:
    return {
        "file_id": str(row[0]),
        "chunk_id": str(row[1]) if row[1] else None,
        "content": row[2] or "",
        "chunk_type": row[3],
        "page_number": row[4],
        "title": row[5],
        "original_name": row[6],
        "version_number": row[7],
        "file_family": row[8],
        "score": float(row[9]),
        "source": source,
    }


_embedding_model = None

def get_query_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding
        from app.config import settings
        _embedding_model = TextEmbedding(
            model_name=settings.LOCAL_EMBEDDING_MODEL,
            threads=4
        )
    return _embedding_model


async def _embed_text(text_input: str) -> Optional[List[float]]:
    """
    Generate a 768-dim embedding using local FastEmbed model.
    """
    try:
        model = get_query_embedding_model()
        emb_vector = list(model.embed([text_input[:8000]]))[0]
        return [float(x) for x in emb_vector]
    except Exception as e:
        import structlog
        structlog.get_logger().error("local_query_embedding_error", error=str(e))
        return None
