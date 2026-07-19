import time
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    File, QueryHistory, WorkspaceMember, WorkspaceRole, AuditLog,
)
from app.schemas import FileOut, QueryRequest, QueryResponse, SourceCitation
from app.config import settings
from app.services.retrieval import (
    get_accessible_file_ids,
    file_metadata_summary_search,
    metadata_search,
    vector_search,
    graph_search,
    get_file_graph_neighbors,
    fuse_results,
    assemble_context,
)
from app.services.llm import generate_answer, select_relevant_files

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = time.time()

    # ── 1. Auth gate ───────────────────────────────────────────────
    membership = await db.execute(
        select(WorkspaceRole.level, WorkspaceRole.role_id)
        .join(WorkspaceMember, WorkspaceMember.role_id == WorkspaceRole.role_id)
        .where(
            WorkspaceMember.workspace_id == payload.workspace_id,
            WorkspaceMember.user_id == current_user.user_id,
        )
    )
    row = membership.one_or_none()
    if row is None:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    my_level, my_role_id = row

    # ── 2. Permission filter ──────────────────────────────────────────
    accessible_ids = await get_accessible_file_ids(
        db, current_user.user_id, payload.workspace_id, my_level, my_role_id
    )
    if not accessible_ids:
        return _no_answer_response(payload.query, payload.workspace_id, start)

    # ── PASS 1: Lightweight metadata scan + LLM file selection ────────
    # Get compact file summaries (title, keywords, tags) — no chunk reads
    summaries = await file_metadata_summary_search(db, payload.query, accessible_ids)

    if not summaries:
        return _no_answer_response(payload.query, payload.workspace_id, start)

    # LLM selects up to 3 relevant files from metadata summaries
    selected_file_id_strs = await select_relevant_files(payload.query, summaries)

    # Map selected string IDs back to UUIDs; fall back to all accessible if LLM returns nothing
    selected_uuids = [UUID(fid) for fid in selected_file_id_strs if _is_valid_uuid(fid)]
    if not selected_uuids:
        selected_uuids = accessible_ids[:3]  # Safe fallback: top 3 accessible

    # ── PASS 2: Multi-source Hybrid Retrieval on selected files ────────
    vec_results = await vector_search(
        db, payload.query, selected_uuids, top_k=settings.RETRIEVAL_TOP_K * 3
    )
    meta_results = await metadata_search(
        db, payload.query, selected_uuids, limit=settings.RETRIEVAL_TOP_K * 3
    )
    graph_results = await graph_search(
        db, payload.query, selected_uuids, workspace_id=payload.workspace_id, limit=settings.RETRIEVAL_TOP_K * 2
    )

    fused_chunks = fuse_results(meta_results, vec_results, graph_results, top_k=settings.RETRIEVAL_TOP_K * 3)

    # If all hybrid retrieval yields nothing (e.g. threshold too strict / no embeddings yet), fallback to raw chunks
    if not fused_chunks:
        from sqlalchemy import text
        result = await db.execute(
            text("""
                SELECT f.file_id, fc.chunk_id, fc.content, fc.chunk_type, fc.page_number,
                       f.title, f.original_name, f.version_number, f.file_family,
                       0.50::float AS score
                FROM file_chunks fc
                JOIN files f ON f.file_id = fc.file_id
                WHERE f.file_id = ANY(:ids)
                ORDER BY f.upload_ts DESC
                LIMIT :top_k
            """),
            {"ids": [str(i) for i in selected_uuids], "top_k": settings.RETRIEVAL_TOP_K * 3},
        )
        from app.services.retrieval import _row_to_chunk_dict
        fused_chunks = [_row_to_chunk_dict(r, source="fallback") for r in result.fetchall()]

    context, citations = await assemble_context(db, fused_chunks)

    if not context:
        return _no_answer_response(payload.query, payload.workspace_id, start)

    # ── PASS 2b: LLM answer ────────────────────────────────────────────
    answer, confidence, model_used = await generate_answer(payload.query, context)

    latency_ms = int((time.time() - start) * 1000)

    # ── PASS 3: One-hop graph neighbors (no LLM) ──────────────────────
    neighbor_ids = await get_file_graph_neighbors(
        db, selected_uuids, accessible_ids, limit=10
    )

    related_file_objs = []
    if neighbor_ids:
        result = await db.execute(
            select(File).where(File.file_id.in_(neighbor_ids[:10]))
        )
        related_file_objs = result.scalars().all()

    # ── Store query history ────────────────────────────────────────────
    query_id = uuid.uuid4()
    db.add(QueryHistory(
        query_id=query_id,
        workspace_id=payload.workspace_id,
        user_id=current_user.user_id,
        query_text=payload.query,
        answer_text=answer,
        source_file_ids=[UUID(c["file_id"]) for c in fused_chunks],
        confidence=confidence,
        no_answer=False,
        model_used=model_used,
        latency_ms=latency_ms,
    ))

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=payload.workspace_id,
        action="query",
        extra={"query": payload.query[:200]},
    ))

    await db.commit()

    return QueryResponse(
        query_id=query_id,
        answer=answer,
        citations=citations,
        related_files=related_file_objs,
        confidence=confidence,
        no_answer=False,
        model_used=model_used,
        latency_ms=latency_ms,
    )


def _is_valid_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except (ValueError, AttributeError):
        return False


def _no_answer_response(query_text: str, workspace_id: UUID, start: float) -> QueryResponse:
    return QueryResponse(
        query_id=uuid.uuid4(),
        answer="No documents in your workspace match this query. Try different keywords or check that relevant files have been uploaded and processed.",
        citations=[],
        related_files=[],
        confidence=0.0,
        no_answer=True,
        model_used="none",
        latency_ms=int((time.time() - start) * 1000),
    )

