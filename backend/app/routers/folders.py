from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_workspace_member
from app.database import get_db
from app.models import (
    AuditLog, File, FileAccessOverride, FileChunk, FileComment, FileEntity,
    FileMetadata, ChunkEmbedding, GraphEdge, GraphNode, User, UserGraphMutation,
    WorkspaceFolder, WorkspaceRole
)
from app.schemas import FolderCreate, FolderOut, FolderUpdate
from app.storage import delete_file as minio_delete

router = APIRouter(prefix="/workspaces/{workspace_id}/folders", tags=["folders"])


@router.get("", response_model=List[FolderOut])
async def list_folders(
    workspace_id: UUID,
    parent_folder_id: Optional[UUID] = Query(None, description="Filter by parent folder (omit for root)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List branches / folders in this workspace.
    Inheritance rules apply when traversing folders.
    """
    await require_workspace_member(current_user, workspace_id, db)

    q = select(WorkspaceFolder).where(WorkspaceFolder.workspace_id == workspace_id)
    if parent_folder_id:
        q = q.where(WorkspaceFolder.parent_folder_id == parent_folder_id)
    else:
        q = q.where(WorkspaceFolder.parent_folder_id.is_(None))

    q = q.order_by(WorkspaceFolder.name.asc())
    result = await db.execute(q)
    folders = result.scalars().all()

    # Attach counts
    out = []
    for f in folders:
        file_count = await db.scalar(
            select(func.count()).where(File.folder_id == f.folder_id)
        )
        sub_count = await db.scalar(
            select(func.count()).where(WorkspaceFolder.parent_folder_id == f.folder_id)
        )
        out.append(FolderOut(
            folder_id=f.folder_id,
            workspace_id=f.workspace_id,
            parent_folder_id=f.parent_folder_id,
            name=f.name,
            description=f.description,
            is_inherited=f.is_inherited,
            allowed_role_ids=f.allowed_role_ids or [],
            min_access_level=f.min_access_level,
            created_at=f.created_at,
            file_count=file_count or 0,
            subfolder_count=sub_count or 0,
        ))
    return out


@router.post("", response_model=FolderOut, status_code=201)
async def create_folder(
    workspace_id: UUID,
    payload: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new branch or folder inside the workspace.
    If overriding inheritance or setting custom ACLs, requires Top Member / Admin check (level 1).
    All creations and policy changes are logged to AuditLog.
    """
    role_id, role_name, my_level = await require_workspace_member(current_user, workspace_id, db)

    if not payload.is_inherited or payload.allowed_role_ids or payload.min_access_level is not None:
        if my_level > 1:
            raise HTTPException(
                status_code=403,
                detail="Only Top Members (Level 1) can configure custom folder ACLs or break inheritance."
            )

    if payload.parent_folder_id:
        parent_res = await db.execute(
            select(WorkspaceFolder).where(
                WorkspaceFolder.folder_id == payload.parent_folder_id,
                WorkspaceFolder.workspace_id == workspace_id,
            )
        )
        if not parent_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Parent folder not found in this workspace")

    folder = WorkspaceFolder(
        workspace_id=workspace_id,
        parent_folder_id=payload.parent_folder_id,
        name=payload.name,
        description=payload.description,
        is_inherited=payload.is_inherited,
        allowed_role_ids=payload.allowed_role_ids or [],
        min_access_level=payload.min_access_level,
    )
    db.add(folder)
    await db.flush()

    # Audit log
    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="folder_create",
        extra={
            "folder_id": str(folder.folder_id),
            "name": folder.name,
            "is_inherited": folder.is_inherited,
            "allowed_role_ids": [str(r) for r in folder.allowed_role_ids],
            "min_access_level": folder.min_access_level,
        }
    ))
    await db.flush()

    return FolderOut(
        folder_id=folder.folder_id,
        workspace_id=folder.workspace_id,
        parent_folder_id=folder.parent_folder_id,
        name=folder.name,
        description=folder.description,
        is_inherited=folder.is_inherited,
        allowed_role_ids=folder.allowed_role_ids or [],
        min_access_level=folder.min_access_level,
        created_at=folder.created_at,
        file_count=0,
        subfolder_count=0,
    )


@router.patch("/{folder_id}", response_model=FolderOut)
async def update_folder(
    workspace_id: UUID,
    folder_id: UUID,
    payload: FolderUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update folder details or access control policy.
    Modifying ACL policy requires Level 1 Top Member authority and creates a policy_change audit log.
    """
    role_id, role_name, my_level = await require_workspace_member(current_user, workspace_id, db)

    res = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.folder_id == folder_id,
            WorkspaceFolder.workspace_id == workspace_id,
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    acl_changed = False
    if payload.is_inherited is not None and payload.is_inherited != folder.is_inherited:
        acl_changed = True
    if payload.allowed_role_ids is not None and set(payload.allowed_role_ids) != set(folder.allowed_role_ids or []):
        acl_changed = True
    if payload.min_access_level != folder.min_access_level and payload.min_access_level is not None:
        acl_changed = True

    if acl_changed and my_level > 1:
        raise HTTPException(
            status_code=403,
            detail="Only Top Members (Level 1) can modify folder access policies."
        )

    if payload.name is not None:
        folder.name = payload.name
    if payload.description is not None:
        folder.description = payload.description
    if payload.is_inherited is not None:
        folder.is_inherited = payload.is_inherited
    if payload.allowed_role_ids is not None:
        folder.allowed_role_ids = payload.allowed_role_ids
    if payload.min_access_level is not None:
        folder.min_access_level = payload.min_access_level

    await db.flush()

    if acl_changed:
        db.add(AuditLog(
            user_id=current_user.user_id,
            workspace_id=workspace_id,
            action="policy_change",
            extra={
                "target_type": "folder",
                "folder_id": str(folder.folder_id),
                "name": folder.name,
                "is_inherited": folder.is_inherited,
                "allowed_role_ids": [str(r) for r in folder.allowed_role_ids],
                "min_access_level": folder.min_access_level,
            }
        ))
        await db.flush()

    file_count = await db.scalar(select(func.count()).where(File.folder_id == folder.folder_id))
    sub_count = await db.scalar(select(func.count()).where(WorkspaceFolder.parent_folder_id == folder.folder_id))

    return FolderOut(
        folder_id=folder.folder_id,
        workspace_id=folder.workspace_id,
        parent_folder_id=folder.parent_folder_id,
        name=folder.name,
        description=folder.description,
        is_inherited=folder.is_inherited,
        allowed_role_ids=folder.allowed_role_ids or [],
        min_access_level=folder.min_access_level,
        created_at=folder.created_at,
        file_count=file_count or 0,
        subfolder_count=sub_count or 0,
    )


async def _cascade_delete_folder_contents(db: AsyncSession, folder: WorkspaceFolder):
    # 1. Find and delete all sub-branches recursively
    sub_res = await db.execute(select(WorkspaceFolder).where(WorkspaceFolder.parent_folder_id == folder.folder_id))
    for sub in sub_res.scalars().all():
        await _cascade_delete_folder_contents(db, sub)

    # 2. Find and permanently delete all files inside this branch/folder
    file_res = await db.execute(select(File).where(File.folder_id == folder.folder_id))
    files = file_res.scalars().all()

    for f in files:
        if f.storage_key:
            try:
                minio_delete(f.storage_key)
            except Exception:
                pass

        chunk_res = await db.execute(select(FileChunk.chunk_id).where(FileChunk.file_id == f.file_id))
        chunk_ids = [c for c in chunk_res.scalars().all()]
        for c_id in chunk_ids:
            await db.execute(ChunkEmbedding.__table__.delete().where(ChunkEmbedding.chunk_id == c_id))
        await db.execute(FileChunk.__table__.delete().where(FileChunk.file_id == f.file_id))

        await db.execute(FileEntity.__table__.delete().where(FileEntity.file_id == f.file_id))
        await db.execute(FileMetadata.__table__.delete().where(FileMetadata.file_id == f.file_id))
        await db.execute(FileComment.__table__.delete().where(FileComment.file_id == f.file_id))
        await db.execute(FileAccessOverride.__table__.delete().where(FileAccessOverride.file_id == f.file_id))

        node_res = await db.execute(
            select(GraphNode.node_id).where(
                GraphNode.workspace_id == f.workspace_id,
                GraphNode.node_type == "file",
                or_(GraphNode.external_id == str(f.file_id), GraphNode.external_id == str(f.document_id))
            )
        )
        for n_id in node_res.scalars().all():
            await db.execute(GraphEdge.__table__.delete().where(or_(GraphEdge.from_node_id == n_id, GraphEdge.to_node_id == n_id)))
            await db.execute(UserGraphMutation.__table__.delete().where(or_(UserGraphMutation.from_node_id == n_id, UserGraphMutation.to_node_id == n_id)))
            await db.execute(GraphNode.__table__.delete().where(GraphNode.node_id == n_id))

        await db.delete(f)

    # 3. Delete any branch-level or folder-specific knowledge graph nodes and edges
    branch_node_res = await db.execute(
        select(GraphNode.node_id).where(
            GraphNode.workspace_id == folder.workspace_id,
            GraphNode.node_type == "branch",
            or_(GraphNode.external_id == str(folder.folder_id), GraphNode.label == folder.name)
        )
    )
    for bn_id in branch_node_res.scalars().all():
        await db.execute(GraphEdge.__table__.delete().where(or_(GraphEdge.from_node_id == bn_id, GraphEdge.to_node_id == bn_id)))
        await db.execute(UserGraphMutation.__table__.delete().where(or_(UserGraphMutation.from_node_id == bn_id, UserGraphMutation.to_node_id == bn_id)))
        await db.execute(GraphNode.__table__.delete().where(GraphNode.node_id == bn_id))

    # 4. Clean up any orphaned entity nodes left behind by deleted branch files
    orphaned_res = await db.execute(
        select(GraphNode.node_id).where(
            GraphNode.workspace_id == folder.workspace_id,
            GraphNode.node_type == "entity",
            ~GraphNode.node_id.in_(select(GraphEdge.from_node_id).where(GraphEdge.workspace_id == folder.workspace_id)),
            ~GraphNode.node_id.in_(select(GraphEdge.to_node_id).where(GraphEdge.workspace_id == folder.workspace_id))
        )
    )
    for o_id in orphaned_res.scalars().all():
        await db.execute(GraphNode.__table__.delete().where(GraphNode.node_id == o_id))

    await db.delete(folder)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    workspace_id: UUID,
    folder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a folder/branch along with all documents, chunks, and graph nodes inside it."""
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    res = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.folder_id == folder_id,
            WorkspaceFolder.workspace_id == workspace_id,
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="folder_delete",
        extra={"folder_id": str(folder_id), "name": folder.name}
    ))
    await _cascade_delete_folder_contents(db, folder)
