"""
Main Celery task: orchestrates file processing pipeline.

Steps per file:
1. Download from MinIO
2. Detect family
3. Parse → extract text + family metadata
4. Chunk
5. Embed chunks
6. Extract entities
7. Build graph nodes/edges
8. Update file processing_status
"""
import hashlib
import uuid
import traceback
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings
from app.workers.celery_app import celery_app

# Sync engine for Celery (Celery is sync)
sync_engine = create_engine(settings.CELERY_DATABASE_URL, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine)

import structlog
logger = structlog.get_logger()


@celery_app.task(
    name="app.workers.tasks.process_file_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_file_task(self, file_id: str):
    """Main file processing pipeline."""
    with SyncSession() as db:
        from app.models import File, FileMetadata, ProcessingStatus
        file_record = db.execute(select(File).where(File.file_id == UUID(file_id))).scalar_one_or_none()

        if not file_record:
            return {"status": "error", "reason": "file_not_found"}

        try:
            # Mark as processing
            logger.info("Starting file processing", file_id=file_id)
            file_record.processing_status = ProcessingStatus.PROCESSING.value
            db.commit()

            # 1. Download from MinIO
            logger.info("Downloading file from storage", storage_key=file_record.storage_key)
            from app.storage import download_file
            content = download_file(file_record.storage_key)

            # 2. Route to family-specific parser
            logger.info("Parsing file content", filename=file_record.original_name, file_family=file_record.file_family)
            from app.workers.parsers import parse_file
            parsed = parse_file(
                content=content,
                filename=file_record.original_name,
                mime_type=file_record.mime_type,
                file_family=file_record.file_family,
            )

            # 3. Update file metadata
            if parsed.get("title") and not file_record.title:
                file_record.title = str(parsed["title"]).replace("\x00", "")
            if parsed.get("language"):
                file_record.language = str(parsed["language"]).replace("\x00", "")

            # Update family-specific metadata
            meta_record = db.execute(
                select(FileMetadata).where(FileMetadata.file_id == UUID(file_id))
            ).scalar_one_or_none()
            if meta_record:
                meta_record.family_data = parsed.get("family_data", {})
            db.commit()

            # 4. Save chunks
            chunks = parsed.get("chunks", [])
            logger.info("Saving chunks", count=len(chunks))
            chunk_records = _save_chunks(db, UUID(file_id), chunks)

            # 5. Generate embeddings (Local fastembed)
            if chunk_records:
                logger.info("Generating embeddings", chunk_count=len(chunk_records))
                _embed_chunks(db, chunk_records)

            # 6. Extract entities
            entities = parsed.get("entities", [])
            logger.info("Saving entities", entity_count=len(entities))
            _save_entities(db, UUID(file_id), entities)

            # 6b. Save keywords to file record for fast metadata search
            kw = parsed.get("keywords", [])
            if kw:
                file_record.keywords = [str(k).replace("\x00", "") for k in kw[:20]]
                logger.info("Saving keywords", count=len(kw[:20]))
                db.commit()

            # 7. Build graph
            logger.info("Building knowledge graph nodes and edges")
            _build_graph(db, file_record)

            # 7b. Extract and save maintenance calendar events
            logger.info("Extracting maintenance calendar events")
            _extract_and_save_calendar_events(db, file_record, chunks, entities)

            # 8. Delete raw audio from MinIO after successful transcription
            #    (only if the parser flagged it — audio family + KEEP_AUDIO_RAW=False)
            family_data = parsed.get("family_data", {})
            if family_data.get("audio_raw_pending_deletion") and file_record.storage_key:
                try:
                    from app.storage import delete_file as minio_delete
                    minio_delete(file_record.storage_key)
                    logger.info(
                        "Deleted raw audio from MinIO to save storage",
                        storage_key=file_record.storage_key,
                    )
                    # Clear the pending flag in metadata to avoid double-delete on retry
                    if meta_record:
                        meta_record.family_data = {
                            **meta_record.family_data,
                            "audio_raw_pending_deletion": False,
                        }
                        db.commit()
                except Exception as del_err:
                    # Non-fatal — log and continue. The file is fully processed.
                    logger.warning(
                        "Failed to delete raw audio from MinIO (non-fatal)",
                        error=str(del_err),
                    )

            # 9. Mark done
            logger.info("Processing complete", file_id=file_id)
            file_record.processing_status = ProcessingStatus.DONE.value
            db.commit()

            return {"status": "done", "file_id": file_id, "chunks": len(chunks)}

        except Exception as exc:
            logger.error("Processing failed", file_id=file_id, error=str(exc), traceback=traceback.format_exc()[:1000])
            try:
                db.rollback()
                file_record = db.execute(select(File).where(File.file_id == UUID(file_id))).scalar_one_or_none()
                if file_record:
                    file_record.processing_status = ProcessingStatus.FAILED.value
                    file_record.processing_error = (str(exc) + "\n\n" + traceback.format_exc())[:2000]
                    db.commit()
            except Exception as e_fail:
                logger.error("Failed to mark file as failed", error=str(e_fail))

            if isinstance(exc, (ValueError, TypeError, KeyError)):
                return {"status": "failed", "error": str(exc)}
            raise self.retry(exc=exc)


@celery_app.task(name="app.workers.tasks.compute_similarity_task")
def compute_similarity_task():
    """
    Nightly batch: compute SIMILAR_TO edges between files based on embedding cosine similarity.
    Only processes recently added files.
    """
    with SyncSession() as db:
        from sqlalchemy import text
        from app.models import GraphNode, GraphEdge

        # Find file pairs with cosine similarity > 0.85 that don't yet have SIMILAR_TO edges
        # This uses pgvector's approximate nearest neighbor
        result = db.execute(text("""
            WITH file_centroids AS (
                SELECT fc.file_id,
                       avg(ce.embedding) AS centroid
                FROM file_chunks fc
                JOIN chunk_embeddings ce ON ce.chunk_id = fc.chunk_id
                GROUP BY fc.file_id
            )
            SELECT a.file_id AS fid_a, b.file_id AS fid_b,
                   1 - (a.centroid <=> b.centroid) AS sim
            FROM file_centroids a, file_centroids b
            WHERE a.file_id < b.file_id
              AND 1 - (a.centroid <=> b.centroid) > 0.85
            LIMIT 1000
        """))
        pairs = result.fetchall()

        for fid_a, fid_b, sim in pairs:
            # Upsert SIMILAR_TO edge in graph
            node_a = db.execute(
                select(GraphNode).where(
                    GraphNode.node_type == "file",
                    GraphNode.external_id == str(fid_a),
                )
            ).scalar_one_or_none()

            node_b = db.execute(
                select(GraphNode).where(
                    GraphNode.node_type == "file",
                    GraphNode.external_id == str(fid_b),
                )
            ).scalar_one_or_none()

            if node_a and node_b:
                # Require that files share at least one common entity before creating SIMILAR_TO match
                shared_ent = db.execute(
                    select(FileEntity.id)
                    .where(
                        FileEntity.file_id == fid_b,
                        func.lower(FileEntity.entity_value).in_(
                            select(func.lower(FileEntity.entity_value)).where(FileEntity.file_id == fid_a)
                        )
                    )
                ).first()
                if not shared_ent:
                    continue

                existing = db.execute(
                    select(GraphEdge).where(
                        GraphEdge.from_node_id == node_a.node_id,
                        GraphEdge.to_node_id == node_b.node_id,
                        GraphEdge.edge_type == "SIMILAR_TO",
                    )
                ).scalar_one_or_none()

                if not existing:
                    db.add(GraphEdge(
                        from_node_id=node_a.node_id,
                        to_node_id=node_b.node_id,
                        edge_type="SIMILAR_TO",
                        weight=float(sim),
                        properties={"similarity": float(sim)},
                    ))

        db.commit()
        return {"status": "done", "pairs_processed": len(pairs)}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _save_chunks(db: Session, file_id: UUID, chunks: List[Dict]) -> List:
    from app.models import FileChunk
    records = []
    for i, chunk in enumerate(chunks):
        content = chunk.get("content", "").replace("\x00", "")
        if not content.strip():
            continue
        c_hash = hashlib.sha256(content.encode()).hexdigest()
        record = FileChunk(
            chunk_id=uuid.uuid4(),
            file_id=file_id,
            chunk_index=i,
            chunk_type=(chunk.get("chunk_type", "paragraph") or "").replace("\x00", ""),
            content=content,
            content_hash=c_hash,
            token_count=len(content) // 4,
            page_number=chunk.get("page_number"),
            slide_number=chunk.get("slide_number"),
            row_start=chunk.get("row_start"),
            row_end=chunk.get("row_end"),
            timestamp_start=chunk.get("timestamp_start"),
            timestamp_end=chunk.get("timestamp_end"),
        )
        db.add(record)
        records.append(record)
    db.flush()
    return records

_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding
        # Use 4 threads to prevent CPU lockups (1500% -> ~350%) while keeping high throughput
        _embedding_model = TextEmbedding(
            model_name=settings.LOCAL_EMBEDDING_MODEL,
            threads=4
        )
    return _embedding_model


def _embed_chunks(db: Session, chunk_records: List) -> None:
    """
    Generate 768-dim embeddings using local FastEmbed model
    and store them in the chunk_embeddings table.
    
    Processes natively in fast batches locally without API rate limits.
    """
    from app.models import ChunkEmbedding
    import structlog
    
    logger = structlog.get_logger()
    model = get_embedding_model()
    # Optimized batch size for section chunks using SIMD instructions
    batch_size = 32

    total_chunks = len(chunk_records)
    for i in range(0, total_chunks, batch_size):
        batch = chunk_records[i:i + batch_size]
        texts = [chunk.content[:8000] for chunk in batch]

        try:
            embeddings = list(model.embed(texts))
            for chunk, emb_vector in zip(batch, embeddings):
                emb = ChunkEmbedding(
                    chunk_id=chunk.chunk_id,
                    embedding=[float(x) for x in emb_vector],
                    model_version=settings.LOCAL_EMBEDDING_MODEL,
                )
                db.add(emb)
            db.flush()
            logger.info("embeddings_progress", processed=min(i + batch_size, total_chunks), total=total_chunks)
        except Exception as e:
            logger.error("local_embed_error", error=str(e))


def _save_entities(db: Session, file_id: UUID, entities: List[Dict]) -> None:
    from app.models import FileEntity
    for ent in entities:
        db.add(FileEntity(
            file_id=file_id,
            entity_type=(ent.get("type", "unknown") or "").replace("\x00", ""),
            entity_value=(ent.get("value", "") or "").replace("\x00", ""),
            confidence=ent.get("confidence", 1.0),
        ))
    db.flush()


def _build_graph(db: Session, file_record) -> None:
    from app.models import GraphNode, GraphEdge, FileEntity
    from sqlalchemy import select, text, or_, and_

    file_id_str = str(file_record.file_id)
    workspace_id = file_record.workspace_id

    # Resolve branch name from folder
    branch = "Root"
    if file_record.folder_id:
        from app.models import WorkspaceFolder
        folder = db.execute(
            select(WorkspaceFolder).where(WorkspaceFolder.folder_id == file_record.folder_id)
        ).scalar_one_or_none()
        if folder:
            branch = folder.name

    # Ensure file node exists; update branch if already present
    file_node = db.execute(
        select(GraphNode).where(
            GraphNode.node_type == "file",
            GraphNode.external_id == file_id_str,
        )
    ).scalar_one_or_none()

    if not file_node:
        file_node = GraphNode(
            node_type="file",
            external_id=file_id_str,
            workspace_id=workspace_id,
            label=file_record.title or file_record.original_name,
            properties={
                "version_number": file_record.version_number,
                "file_family": file_record.file_family,
                "status": file_record.status,
                "branch": branch,
            },
        )
        db.add(file_node)
        db.flush()
    else:
        # Update branch and label in case they changed
        props = dict(file_node.properties or {})
        props["branch"] = branch
        props["file_family"] = file_record.file_family
        props["status"] = file_record.status
        file_node.properties = props
        file_node.label = file_record.title or file_record.original_name

    # Version chain: if this has a parent, add SUPERSEDED_BY edge
    if file_record.parent_file_id:
        parent_node = db.execute(
            select(GraphNode).where(
                GraphNode.node_type == "file",
                GraphNode.external_id == str(file_record.parent_file_id),
            )
        ).scalar_one_or_none()

        if parent_node:
            # Avoid duplicate SUPERSEDED_BY edges
            existing = db.execute(
                select(GraphEdge).where(
                    GraphEdge.from_node_id == parent_node.node_id,
                    GraphEdge.to_node_id == file_node.node_id,
                    GraphEdge.edge_type == "SUPERSEDED_BY",
                )
            ).scalar_one_or_none()
            if not existing:
                db.add(GraphEdge(
                    from_node_id=parent_node.node_id,
                    to_node_id=file_node.node_id,
                    edge_type="SUPERSEDED_BY",
                ))

    # Add entity/asset nodes and BELONGS_TO_ASSET / MENTIONS edges
    entities = db.execute(
        select(FileEntity).where(FileEntity.file_id == file_record.file_id)
    ).scalars().all()

    max_graph_entities = 150
    for ent in entities[:max_graph_entities]:  # Keep up to 150 graph nodes for both small and large documents
        ent_val = ent.entity_value.strip().upper() if ent.entity_value else ""
        if len(ent_val) < 2:
            continue
        ent_type = ent.entity_type.lower()
        node_type = "asset" if ent_type in ("equipment", "asset", "tag", "p&id") or any(ch.isdigit() for ch in ent_val) else "entity"

        ent_node = db.execute(
            select(GraphNode).where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.external_id == ent_val,
                GraphNode.node_type.in_(["asset", "entity"]),
            )
        ).scalar_one_or_none()

        if not ent_node:
            ent_node = GraphNode(
                node_type=node_type,
                external_id=ent_val,
                workspace_id=workspace_id,
                label=ent_val,
                properties={"entity_type": ent.entity_type, "branch": "Entities"},
            )
            db.add(ent_node)
            db.flush()

        edge_type = "BELONGS_TO_ASSET" if node_type == "asset" else "MENTIONS"
        existing_edge = db.execute(
            select(GraphEdge).where(
                GraphEdge.from_node_id == file_node.node_id,
                GraphEdge.to_node_id == ent_node.node_id,
                GraphEdge.edge_type == edge_type,
            )
        ).scalar_one_or_none()

        if not existing_edge:
            db.add(GraphEdge(
                from_node_id=file_node.node_id,
                to_node_id=ent_node.node_id,
                edge_type=edge_type,
                weight=float(ent.confidence or 0.8),
            ))

    db.flush()

    # Compute immediate SIMILAR_TO edges with existing files in workspace if embeddings exist
    try:
        res = db.execute(text("""
            WITH my_centroid AS (
                SELECT avg(ce.embedding) AS centroid
                FROM file_chunks fc
                JOIN chunk_embeddings ce ON ce.chunk_id = fc.chunk_id
                WHERE fc.file_id = :fid
            ),
            other_centroids AS (
                SELECT fc.file_id, avg(ce.embedding) AS centroid
                FROM file_chunks fc
                JOIN chunk_embeddings ce ON ce.chunk_id = fc.chunk_id
                JOIN files f ON f.file_id = fc.file_id
                WHERE f.workspace_id = :wid
                  AND fc.file_id != :fid
                GROUP BY fc.file_id
            )
            SELECT o.file_id, 1 - (m.centroid <=> o.centroid) AS sim
            FROM my_centroid m, other_centroids o
            WHERE m.centroid IS NOT NULL AND o.centroid IS NOT NULL
              AND 1 - (m.centroid <=> o.centroid) > 0.75
            LIMIT 10
        """), {"fid": str(file_record.file_id), "wid": str(workspace_id)})
        similar_pairs = res.fetchall()

        for other_fid, sim_score in similar_pairs:
            other_node = db.execute(
                select(GraphNode).where(
                    GraphNode.node_type == "file",
                    GraphNode.external_id == str(other_fid),
                )
            ).scalar_one_or_none()

            if other_node and other_node.node_id != file_node.node_id:
                # Require that both files share at least one similar/common entity
                shared_ent_check = db.execute(
                    select(FileEntity.id)
                    .where(
                        FileEntity.file_id == other_fid,
                        func.lower(FileEntity.entity_value).in_(
                            select(func.lower(FileEntity.entity_value)).where(FileEntity.file_id == file_record.file_id)
                        )
                    )
                ).first()
                if not shared_ent_check:
                    continue

                existing_sim = db.execute(
                    select(GraphEdge).where(
                        or_(
                            and_(GraphEdge.from_node_id == file_node.node_id, GraphEdge.to_node_id == other_node.node_id),
                            and_(GraphEdge.from_node_id == other_node.node_id, GraphEdge.to_node_id == file_node.node_id)
                        ),
                        GraphEdge.edge_type == "SIMILAR_TO",
                    )
                ).scalar_one_or_none()

                if not existing_sim:
                    db.add(GraphEdge(
                        from_node_id=file_node.node_id,
                        to_node_id=other_node.node_id,
                        edge_type="SIMILAR_TO",
                        weight=float(sim_score),
                        properties={"similarity": float(sim_score)},
                    ))
        db.flush()
    except Exception as sim_err:
        import structlog
        structlog.get_logger().warning("build_graph_similarity_error", error=str(sim_err))

    db.flush()


def _extract_and_save_calendar_events(db: Session, file_record, chunks: List[Dict], entities: List[Dict]) -> None:
    import asyncio
    from datetime import datetime, timezone
    from app.models import MaintenanceEvent, GraphNode, GraphEdge
    from app.services.calendar_agent import extract_events_from_document

    # Build full or sample text from chunks
    full_text = "\n\n".join([c.get("content", "") for c in chunks[:40]])
    if not full_text.strip():
        return

    # Extract equipment tags from entities
    equipment_tags = [
        str(ent.get("value", "")).strip() for ent in entities 
        if ent.get("type", "").lower() in ("equipment", "asset", "tag", "p&id") or any(ch.isdigit() for ch in str(ent.get("value", "")))
    ]

    try:
        # Run async calendar extraction synchronously in Celery worker thread
        loop = asyncio.new_event_loop()
        try:
            events_data = loop.run_until_complete(
                extract_events_from_document(full_text, str(file_record.file_id), file_record.workspace_id, equipment_tags)
            )
        finally:
            loop.close()

        if not events_data:
            return

        # Find file node in graph if it exists
        file_node = db.execute(
            select(GraphNode).where(
                GraphNode.node_type == "file",
                GraphNode.external_id == str(file_record.file_id),
            )
        ).scalar_one_or_none()

        for ev in events_data:
            start_dt = None
            if ev.get("start_at"):
                try:
                    start_dt = datetime.fromisoformat(str(ev["start_at"]).replace("Z", "+00:00"))
                except Exception:
                    start_dt = datetime.now(timezone.utc)

            m_event = MaintenanceEvent(
                workspace_id=file_record.workspace_id,
                title=str(ev.get("title", "Maintenance Task"))[:512],
                equipment_id=str(ev.get("equipment_id", "")[:256]) if ev.get("equipment_id") else None,
                event_type=str(ev.get("event_type", "preventive"))[:64],
                start_at=start_dt,
                end_at=None,
                repeat_rule=str(ev.get("repeat_rule", ""))[:256] if ev.get("repeat_rule") else None,
                description=str(ev.get("description", ""))[:2000],
                source_type="document",
                source_id=str(file_record.file_id),
                confidence=str(ev.get("confidence", "medium"))[:32],
            )
            db.add(m_event)
            db.flush()

            # Create event node in Knowledge Graph
            ev_node = GraphNode(
                node_type="event",
                external_id=str(m_event.event_id),
                workspace_id=file_record.workspace_id,
                label=m_event.title[:255],
                properties={
                    "event_type": m_event.event_type,
                    "repeat_rule": m_event.repeat_rule,
                    "start_at": m_event.start_at.isoformat() if m_event.start_at else None,
                    "branch": "Schedules",
                },
            )
            db.add(ev_node)
            db.flush()

            # Link event to document
            if file_node:
                db.add(GraphEdge(
                    from_node_id=ev_node.node_id,
                    to_node_id=file_node.node_id,
                    edge_type="SCHEDULED_IN",
                    weight=0.9 if m_event.confidence == "high" else 0.7,
                ))

            # Link event to asset/equipment node if equipment_id is present
            if m_event.equipment_id:
                asset_node = db.execute(
                    select(GraphNode).where(
                        GraphNode.workspace_id == file_record.workspace_id,
                        GraphNode.external_id == m_event.equipment_id.upper(),
                        GraphNode.node_type.in_(["asset", "entity"]),
                    )
                ).scalar_one_or_none()
                if asset_node:
                    db.add(GraphEdge(
                        from_node_id=ev_node.node_id,
                        to_node_id=asset_node.node_id,
                        edge_type="SCHEDULED_FOR",
                        weight=0.95,
                    ))

        db.commit()
        logger.info("Saved and graphed maintenance calendar events", count=len(events_data))
    except Exception as exc:
        logger.warning("failed_to_save_calendar_events", error=str(exc))
        db.rollback()
