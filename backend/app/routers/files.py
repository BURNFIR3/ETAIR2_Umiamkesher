import mimetypes
import uuid
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File as FastAPIFile, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_workspace_member
from app.config import settings
from app.database import get_db
from app.models import (
    AuditLog, File, FileComment, FileEntity, FileMetadata, FileAccessOverride,
    FileChunk, ChunkEmbedding, GraphNode, GraphEdge, UserGraphMutation,
    Workspace, WorkspaceFolder, WorkspaceMember, WorkspaceRole
)
from app.schemas import CommentCreate, CommentOut, FileOut, FileStatusUpdate, FileVersionOut, UpdateFileACL
from app.storage import build_storage_key, compute_sha256, upload_file as minio_upload, delete_file as minio_delete, get_presigned_url
from app.utils.file_detection import detect_file_family
from app.workers.tasks import process_file_task
from app.services.retrieval import get_accessible_file_ids, get_accessible_file_ids_any_status

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload/{workspace_id}", response_model=FileOut, status_code=201)
async def upload_file(
    workspace_id: UUID,
    file: UploadFile = FastAPIFile(...),
    document_id: Optional[str] = Form(None),        # if replacing a version, pass existing document_id
    folder_id: Optional[str] = Form(None),          # target branch / folder
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),               # comma-separated
    is_inherited: Optional[bool] = Form(True),      # inherit ACL from folder/workspace
    allowed_role_ids: Optional[str] = Form(None),   # comma-separated role IDs for file-level ACL
    min_access_level: Optional[int] = Form(None),   # NULL = all members; N = only level ≤ N users
    status: str = Form("draft"),                    # allow user to select draft, approved, etc.
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role_id, _, my_level = await require_workspace_member(current_user, workspace_id, db)

    # Read file content
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    content_hash = compute_sha256(content)
    mime = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    family = detect_file_family(file.filename, mime)

    # Resolve document_id (new document or new version of existing)
    if document_id:
        doc_uuid = UUID(document_id)
        # Find latest version
        result = await db.execute(
            select(File).where(
                File.document_id == doc_uuid,
                File.workspace_id == workspace_id,
            ).order_by(File.version_number.desc()).limit(1)
        )
        parent_file = result.scalar_one_or_none()
        if not parent_file:
            raise HTTPException(status_code=404, detail="Document not found in this workspace")
        version_number = parent_file.version_number + 1
        parent_file_id = parent_file.file_id
    else:
        doc_uuid = uuid.uuid4()
        version_number = 1
        parent_file_id = None

    # Build storage key and upload to MinIO / Supabase S3
    storage_key = build_storage_key(str(workspace_id), str(doc_uuid), version_number, file.filename)
    try:
        minio_upload(content, storage_key, mime)
    except Exception as s3_err:
        import structlog as _slog
        _slog.get_logger().error("storage_upload_failed", error=str(s3_err), storage_key=storage_key)
        raise HTTPException(
            status_code=503,
            detail=f"Storage upload failed: {s3_err}. Check MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY and that the '{settings.MINIO_BUCKET_FILES}' bucket exists.",
        )

    # Parse tags and role ACLs
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    role_id_list = [UUID(r.strip()) for r in allowed_role_ids.split(",") if r.strip()] if allowed_role_ids else []
    folder_uuid = UUID(folder_id) if folder_id else None

    # Create File record
    db_file = File(
        document_id=doc_uuid,
        workspace_id=workspace_id,
        folder_id=folder_uuid,
        version_number=version_number,
        parent_file_id=parent_file_id,
        original_name=file.filename,
        storage_key=storage_key,
        content_hash=content_hash,
        mime_type=mime,
        file_family=family,
        file_size_bytes=len(content),
        uploader_id=current_user.user_id,
        uploader_level=my_level,
        title=title or file.filename,
        description=description,
        tags=tag_list,
        is_inherited=is_inherited if is_inherited is not None else True,
        allowed_role_ids=role_id_list,
        min_access_level=min_access_level,
        status=status,
        processing_status="pending",
    )
    db.add(db_file)
    await db.flush()

    # Initialize metadata record
    db.add(FileMetadata(file_id=db_file.file_id, family_data={}))

    # Audit log
    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=db_file.file_id,
        workspace_id=workspace_id,
        action="upload",
    ))

    await db.flush()

    # ── CRITICAL: commit the transaction BEFORE dispatching the Celery task.
    # The Celery worker uses a separate synchronous DB engine (psycopg2).
    # If we don't commit here, the worker's SELECT will find no row and fail
    # with {"status": "error", "reason": "file_not_found"} on every upload.
    await db.commit()

    # ── Dispatch async processing task ────────────────────────────────────────
    # Check if there is an active Celery worker listening.
    # On Render Free Web Service deployments, users often provide a valid Upstash REDIS_URL 
    # but don't deploy a separate Celery worker. In that case, `.delay()` succeeds and queues 
    # the task in Redis indefinitely.
    has_workers = False
    try:
        from app.workers.celery_app import celery_app
        # Ping workers with a 0.5s timeout.
        # Returns [] if broker is up but no workers attached.
        # Raises exception if broker is down.
        ping_result = celery_app.control.ping(timeout=0.5)
        has_workers = bool(ping_result)
    except Exception as ping_err:
        import structlog as _slog
        _slog.get_logger().warning("celery_broker_ping_failed", error=str(ping_err))
        has_workers = False

    if has_workers:
        process_file_task.delay(str(db_file.file_id))
    else:
        import asyncio
        import structlog as _slog
        _slog.get_logger().info(
            "no_celery_workers_found_running_inline",
            file_id=str(db_file.file_id)
        )
        
        def _run_inline(fid: str):
            try:
                # Calling the task object directly handles the `bind=True` self injection.
                process_file_task(fid)
            except Exception as e:
                _slog.get_logger().error("inline_processing_fatal_error", file_id=fid, error=str(e), exc_info=True)
                
        _file_id_str = str(db_file.file_id)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run_inline, _file_id_str)

    return db_file


@router.get("/workspace/{workspace_id}", response_model=List[FileOut])
async def list_workspace_files(
    workspace_id: UUID,
    folder_id: Optional[UUID] = Query(None, description="Filter by folder ID (omit for all or pass specific folder)"),
    all_folders: bool = Query(False, description="Set true to return files across all folders/branches"),
    status: Optional[str] = Query(None),
    family: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role_id, _, my_level = await require_workspace_member(current_user, workspace_id, db)

    accessible_ids = await get_accessible_file_ids_any_status(
        db, current_user.user_id, workspace_id, my_level, role_id
    )

    q = select(File).where(
        File.workspace_id == workspace_id,
        File.file_id.in_(accessible_ids),
    )

    if folder_id:
        q = q.where(File.folder_id == folder_id)
    elif not all_folders:
        q = q.where(File.folder_id.is_(None))

    if status:
        q = q.where(File.status == status)
    if family:
        q = q.where(File.file_family == family)
    if search:
        q = q.where(
            or_(
                File.title.ilike(f"%{search}%"),
                File.original_name.ilike(f"%{search}%"),
                File.description.ilike(f"%{search}%"),
            )
        )

    q = q.order_by(File.upload_ts.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{file_id}", response_model=FileOut)
async def get_file(
    file_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(File).where(File.file_id == file_id))
    file = res.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    role_id, _, my_level = await require_workspace_member(current_user, file.workspace_id, db)
    accessible_ids = await get_accessible_file_ids(
        db, current_user.user_id, file.workspace_id, my_level, role_id
    )
    if file.file_id not in accessible_ids and my_level > 1:
        raise HTTPException(status_code=403, detail="Access denied by document governance policy")

    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=file.file_id,
        workspace_id=file.workspace_id,
        action="view",
    ))
    return file


@router.patch("/{file_id}/acl", response_model=FileOut)
async def update_file_acl(
    file_id: UUID,
    payload: UpdateFileACL,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update document-level ACL exceptions (`allowed_role_ids`, `is_inherited`, `min_access_level`, `folder_id`).
    Requires Level 1 Top Member authority (or document uploader if level <= 2).
    Generates an AuditLog entry with action='policy_change'.
    """
    res = await db.execute(select(File).where(File.file_id == file_id))
    file = res.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    role_id, _, my_level = await require_workspace_member(current_user, file.workspace_id, db)
    if my_level > 1 and file.uploader_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="Only Level 1 Top Members or the original uploader can modify document ACL exceptions."
        )

    if payload.folder_id is not None:
        file.folder_id = payload.folder_id
    if payload.is_inherited is not None:
        file.is_inherited = payload.is_inherited
    if payload.allowed_role_ids is not None:
        file.allowed_role_ids = payload.allowed_role_ids
    if payload.min_access_level is not None:
        file.min_access_level = payload.min_access_level

    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=file.file_id,
        workspace_id=file.workspace_id,
        action="policy_change",
        extra={
            "target_type": "file",
            "file_id": str(file.file_id),
            "folder_id": str(file.folder_id) if file.folder_id else None,
            "is_inherited": file.is_inherited,
            "allowed_role_ids": [str(r) for r in file.allowed_role_ids],
            "min_access_level": file.min_access_level,
        }
    ))
    await db.flush()
    return file


@router.get("/{file_id}/download-url")
async def get_download_url(
    file_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    await require_workspace_member(current_user, f.workspace_id, db)

    url = get_presigned_url(f.storage_key, expires_seconds=1800)

    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=f.file_id,
        workspace_id=f.workspace_id,
        action="download",
    ))
    return {"url": url, "filename": f.original_name, "expires_in": 1800}


@router.get("/{file_id}/versions", response_model=List[FileVersionOut])
async def get_file_versions(
    file_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Get the document_id of this file
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    await require_workspace_member(current_user, f.workspace_id, db)

    versions = await db.execute(
        select(File).where(File.document_id == f.document_id).order_by(File.version_number.asc())
    )
    return versions.scalars().all()


@router.patch("/{file_id}/status", response_model=FileOut)
async def update_file_status(
    file_id: UUID,
    payload: FileStatusUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    # Require at least Level-2 authority (i.e. level <= 2) to change document status.
    # Level 1 = top member / admin; level 2 = document controller equivalent.
    _, _, my_level = await require_workspace_member(current_user, f.workspace_id, db, max_level=2)

    f.status = payload.status
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=f.file_id,
        workspace_id=f.workspace_id,
        action=f"status_change:{payload.status}",
    ))
    return f


@router.get("/workspace/{workspace_id}/archived", response_model=List[FileOut])
async def list_archived_files(
    workspace_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all archived files in the workspace that the current user can access.
    Archived files are excluded from regular retrieval but can be viewed here
    by any workspace member, and restored by Level-1/2 members.
    """
    role_id, _, my_level = await require_workspace_member(current_user, workspace_id, db)

    accessible_ids = await get_accessible_file_ids_any_status(
        db, current_user.user_id, workspace_id, my_level, role_id
    )

    q = (
        select(File)
        .where(
            File.workspace_id == workspace_id,
            File.file_id.in_(accessible_ids),
            File.status == "archived",
        )
        .order_by(File.upload_ts.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/{file_id}/restore", response_model=FileOut)
async def restore_file(
    file_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Restore a previously archived file back to 'draft' status.
    Requires Level-1 or Level-2 authority (document controller equivalent).
    An audit log entry is recorded for governance traceability.
    """
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    _, _, my_level = await require_workspace_member(current_user, f.workspace_id, db, max_level=2)

    if f.status != "archived":
        raise HTTPException(
            status_code=400,
            detail=f"Only archived files can be restored. Current status: '{f.status}'.",
        )

    f.status = "draft"
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=f.file_id,
        workspace_id=f.workspace_id,
        action="status_change:draft",
        extra={"restored_from": "archived"},
    ))
    return f


@router.post("/{file_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    file_id: UUID,
    payload: CommentCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    await require_workspace_member(current_user, f.workspace_id, db)

    comment = FileComment(
        file_id=file_id,
        user_id=current_user.user_id,
        content=payload.content,
        page_number=payload.page_number,
    )
    db.add(comment)
    await db.flush()
    return comment


@router.get("/{file_id}/comments", response_model=List[CommentOut])
async def list_comments(
    file_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    await require_workspace_member(current_user, f.workspace_id, db)

    comments = await db.execute(
        select(FileComment).where(FileComment.file_id == file_id).order_by(FileComment.created_at)
    )
    return comments.scalars().all()


@router.delete("/{file_id}", status_code=200)
async def delete_file(
    file_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Hard delete a file and all its corresponding knowledge graph entries, embeddings,
    text chunks, entities, metadata, comments, ACL overrides, and MinIO binary objects.
    This action is permanent and requires confirmation from the UI.
    """
    result = await db.execute(select(File).where(File.file_id == file_id))
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    await require_workspace_member(current_user, f.workspace_id, db)

    # 1. Delete binary object from MinIO if storage_key is set
    if f.storage_key:
        try:
            minio_delete(f.storage_key)
        except Exception as e:
            import structlog
            structlog.get_logger().warning("minio_delete_error", error=str(e), storage_key=f.storage_key)

    # 2. Delete all embeddings associated with this file's chunks
    chunk_res = await db.execute(select(FileChunk.chunk_id).where(FileChunk.file_id == file_id))
    chunk_ids = [c for c in chunk_res.scalars().all()]
    if chunk_ids:
        for c_id in chunk_ids:
            await db.execute(ChunkEmbedding.__table__.delete().where(ChunkEmbedding.chunk_id == c_id))
        await db.execute(FileChunk.__table__.delete().where(FileChunk.file_id == file_id))

    # 3. Delete file entities, metadata, comments, ACL overrides
    file_ents_res = await db.execute(select(FileEntity).where(FileEntity.file_id == file_id))
    my_entities = file_ents_res.scalars().all()
    my_ent_texts = {fe.entity_value.strip().lower() for fe in my_entities if fe.entity_value}

    await db.execute(FileEntity.__table__.delete().where(FileEntity.file_id == file_id))
    await db.execute(FileMetadata.__table__.delete().where(FileMetadata.file_id == file_id))
    await db.execute(FileComment.__table__.delete().where(FileComment.file_id == file_id))
    await db.execute(FileAccessOverride.__table__.delete().where(FileAccessOverride.file_id == file_id))

    # 4. Delete corresponding Knowledge Graph nodes and incident edges / mutations
    # Check both str(file_id) and str(f.document_id) for external_id matches
    node_res = await db.execute(
        select(GraphNode.node_id).where(
            GraphNode.workspace_id == f.workspace_id,
            GraphNode.node_type == "file",
            or_(GraphNode.external_id == str(file_id), GraphNode.external_id == str(f.document_id))
        )
    )
    node_ids = [n for n in node_res.scalars().all()]
    if node_ids:
        for n_id in node_ids:
            await db.execute(
                GraphEdge.__table__.delete().where(
                    or_(GraphEdge.from_node_id == n_id, GraphEdge.to_node_id == n_id)
                )
            )
            await db.execute(
                UserGraphMutation.__table__.delete().where(
                    or_(UserGraphMutation.from_node_id == n_id, UserGraphMutation.to_node_id == n_id)
                )
            )
            await db.execute(GraphNode.__table__.delete().where(GraphNode.node_id == n_id))

    # Clean up entities not connected to or referenced by any other file in the workspace
    if my_ent_texts:
        for ent_text in my_ent_texts:
            other_res = await db.execute(
                select(FileEntity.id)
                .join(File, File.file_id == FileEntity.file_id)
                .where(
                    File.workspace_id == f.workspace_id,
                    FileEntity.file_id != file_id,
                    func.lower(FileEntity.entity_value) == ent_text
                )
            )
            if not other_res.first():
                ent_nodes_res = await db.execute(
                    select(GraphNode.node_id).where(
                        GraphNode.workspace_id == f.workspace_id,
                        func.lower(GraphNode.label) == ent_text,
                        GraphNode.node_type != "file"
                    )
                )
                for ent_nid in ent_nodes_res.scalars().all():
                    await db.execute(GraphEdge.__table__.delete().where(
                        or_(GraphEdge.from_node_id == ent_nid, GraphEdge.to_node_id == ent_nid)
                    ))
                    await db.execute(UserGraphMutation.__table__.delete().where(
                        or_(UserGraphMutation.from_node_id == ent_nid, UserGraphMutation.to_node_id == ent_nid)
                    ))
                    await db.execute(GraphNode.__table__.delete().where(GraphNode.node_id == ent_nid))

    # Clean up any orphaned non-system nodes that now have zero edges left
    orphan_res = await db.execute(
        select(GraphNode.node_id).where(
            GraphNode.workspace_id == f.workspace_id,
            GraphNode.node_type.notin_(["file", "document", "workspace", "folder", "role", "person"]),
            ~GraphNode.node_id.in_(select(GraphEdge.from_node_id)),
            ~GraphNode.node_id.in_(select(GraphEdge.to_node_id))
        )
    )
    for orphan_id in orphan_res.scalars().all():
        await db.execute(UserGraphMutation.__table__.delete().where(
            or_(UserGraphMutation.from_node_id == orphan_id, UserGraphMutation.to_node_id == orphan_id)
        ))
        await db.execute(GraphNode.__table__.delete().where(GraphNode.node_id == orphan_id))

    # 5. Nullify foreign key references in AuditLog and child files so deleting File won't cause FK violations
    await db.execute(update(AuditLog).where(AuditLog.file_id == file_id).values(file_id=None))
    await db.execute(update(File).where(File.parent_file_id == file_id).values(parent_file_id=None))

    # 6. Record audit log (without setting FK file_id since the file row is being deleted)
    db.add(AuditLog(
        user_id=current_user.user_id,
        file_id=None,
        workspace_id=f.workspace_id,
        action="file_hard_delete",
        extra={"deleted_file_id": str(file_id), "title": f.title or f.original_name, "version": f.version_number},
    ))
    await db.delete(f)
    await db.commit()

    return {"detail": f"File '{f.original_name}' and all associated knowledge graph and embedding data permanently deleted."}

