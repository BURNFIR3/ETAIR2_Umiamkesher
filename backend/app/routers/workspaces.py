import re
import uuid
from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_workspace_member
from app.database import get_db
from app.models import AuditLog, File, User, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas import (
    AuditLogOut, InviteMember, MemberOut, RoleCreate, RoleOut, RoleUpdate,
    SwapLevelsRequest, UpdateMemberRole,
    WorkspaceCreate, WorkspaceDeleteRequest, WorkspaceDetailOut, WorkspaceOut,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# Level 1 is the top authority role that gets auto-created for workspace creator
DEFAULT_ADMIN_LEVEL = 1
DEFAULT_ADMIN_NAME = "Administrator"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug}-{uuid.uuid4().hex[:6]}"


# ─── Workspaces ───────────────────────────────────────────────────────────────

@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = Workspace(
        name=payload.name,
        slug=slugify(payload.name),
        description=payload.description,
        industry=payload.industry,
        site_location=payload.site_location,
        created_by=current_user.user_id,
    )
    db.add(ws)
    await db.flush()

    # Auto-create Level 1 "Administrator" role
    admin_role = WorkspaceRole(
        workspace_id=ws.workspace_id,
        name=DEFAULT_ADMIN_NAME,
        level=DEFAULT_ADMIN_LEVEL,
        description="Full authority over the workspace. Created automatically.",
        can_modify_graph=True,
    )
    db.add(admin_role)
    await db.flush()

    # Assign creator to Level 1
    member = WorkspaceMember(
        workspace_id=ws.workspace_id,
        user_id=current_user.user_id,
        role_id=admin_role.role_id,
    )
    db.add(member)
    return ws


@router.get("", response_model=List[WorkspaceOut])
async def list_my_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.workspace_id)
        .where(
            WorkspaceMember.user_id == current_user.user_id,
            Workspace.is_deleted == False,  # noqa: E712  — exclude soft-deleted
        )
        .order_by(Workspace.created_at.desc())
    )
    return result.scalars().all()


@router.get("/archived", response_model=List[WorkspaceOut])
async def list_archived_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Feature 2 — Orphaned Safe House.
    Returns all soft-deleted workspaces where the current user was (and still is)
    a Level 1 Administrator. WorkspaceMembers records are intentionally kept intact
    on soft-delete (NO CASCADE) to preserve historical admin authority for restoration.
    """
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.workspace_id)
        .join(WorkspaceRole, WorkspaceRole.role_id == WorkspaceMember.role_id)
        .where(
            WorkspaceMember.user_id == current_user.user_id,
            WorkspaceRole.level == DEFAULT_ADMIN_LEVEL,
            Workspace.is_deleted == True,  # noqa: E712
        )
        .order_by(Workspace.deleted_at.desc())
    )
    return result.scalars().all()


@router.get("/{workspace_id}", response_model=WorkspaceDetailOut)
async def get_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, role_name, level = await require_workspace_member(current_user, workspace_id, db)

    result = await db.execute(select(Workspace).where(Workspace.workspace_id == workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.is_deleted:
        raise HTTPException(
            status_code=410,
            detail="This workspace has been soft-deleted. Use GET /workspaces/archived to find it and POST /restore to recover it."
        )

    member_count = await db.scalar(
        select(func.count()).where(WorkspaceMember.workspace_id == workspace_id)
    )
    file_count = await db.scalar(
        select(func.count()).where(File.workspace_id == workspace_id)
    )

    return WorkspaceDetailOut(
        **WorkspaceOut.model_validate(ws).model_dump(),
        member_count=member_count or 0,
        file_count=file_count or 0,
        my_role_name=role_name,
        my_role_level=level,
    )


@router.post("/{workspace_id}/delete", status_code=200)
async def soft_delete_workspace(
    workspace_id: UUID,
    payload: WorkspaceDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Gate 1: Verify Level 1 Admin membership or creator/superuser
    member_res = await db.execute(
        select(WorkspaceMember, WorkspaceRole)
        .join(WorkspaceRole, WorkspaceRole.role_id == WorkspaceMember.role_id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.user_id,
        )
    )
    row = member_res.one_or_none()
    
    # Load workspace
    ws_res = await db.execute(select(Workspace).where(Workspace.workspace_id == workspace_id))
    ws = ws_res.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.is_deleted:
        raise HTTPException(status_code=409, detail="Workspace is already deleted.")

    if not current_user.is_superuser and ws.created_by != current_user.user_id:
        if not row:
            raise HTTPException(status_code=403, detail="You are not a member of this workspace.")
        _, member_role = row
        if member_role.level != DEFAULT_ADMIN_LEVEL and not getattr(member_role, "can_modify_graph", False):
            raise HTTPException(
                status_code=403,
                detail="Only Level 1 Administrators can delete a workspace."
            )

    # Gate 2: Name confirmation
    if payload.confirmation_name != ws.name:
        raise HTTPException(
            status_code=400,
            detail=f"Name confirmation mismatch. Type the exact workspace name '{ws.name}' to confirm deletion."
        )

    # Soft delete
    ws.is_deleted = True
    ws.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="workspace_soft_delete",
        extra={"confirmed_name": payload.confirmation_name},
    ))
    await db.commit()

    return {"detail": f"Workspace '{ws.name}' has been soft-deleted and moved to the archive."}


@router.post("/{workspace_id}/restore", status_code=200)
async def restore_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Restore a soft-deleted workspace back to active status.
    Must be a historical Level 1 Admin, creator, or superuser.
    """
    ws_res = await db.execute(select(Workspace).where(Workspace.workspace_id == workspace_id))
    ws = ws_res.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not ws.is_deleted:
        raise HTTPException(status_code=409, detail="Workspace is not deleted and does not need restoration.")

    if not current_user.is_superuser and ws.created_by != current_user.user_id:
        member_res = await db.execute(
            select(WorkspaceMember, WorkspaceRole)
            .join(WorkspaceRole, WorkspaceRole.role_id == WorkspaceMember.role_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == current_user.user_id,
            )
        )
        row = member_res.one_or_none()
        if not row:
            raise HTTPException(status_code=403, detail="You are not (or were not) a member of this workspace.")
        _, member_role = row
        if member_role.level != DEFAULT_ADMIN_LEVEL and not getattr(member_role, "can_modify_graph", False):
            raise HTTPException(
                status_code=403,
                detail="Only a historical Level 1 Administrator can restore a workspace."
            )

    # Restore
    ws.is_deleted = False
    ws.deleted_at = None
    await db.commit()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="workspace_restore",
        extra={},
    ))
    await db.commit()

    return {"detail": f"Workspace '{ws.name}' has been successfully restored."}


@router.delete("/{workspace_id}/permanent", status_code=200)
async def delete_workspace_permanent(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Feature: Permanently hard-delete a soft-deleted workspace from the graveyard (and all its files, data, and graphs).
    Only a historical Level 1 Admin can permanently delete a workspace.
    """
    ws_res = await db.execute(select(Workspace).where(Workspace.workspace_id == workspace_id))
    ws = ws_res.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Verify user is a Level 1 Admin (historical record must still exist) or superuser/creator
    if not current_user.is_superuser and ws.created_by != current_user.user_id:
        member_res = await db.execute(
            select(WorkspaceMember, WorkspaceRole)
            .join(WorkspaceRole, WorkspaceRole.role_id == WorkspaceMember.role_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == current_user.user_id,
            )
        )
        row = member_res.one_or_none()
        if not row:
            raise HTTPException(status_code=403, detail="You are not (or were not) a member of this workspace.")
        _, member_role = row
        if member_role.level != DEFAULT_ADMIN_LEVEL and not getattr(member_role, "can_modify_graph", False):
            raise HTTPException(
                status_code=403,
                detail="Only a historical Level 1 Administrator can permanently delete a workspace."
            )

    from app.models import (
        AuditLog, File, FileComment, FileEntity, FileMetadata, FileAccessOverride,
        FileChunk, ChunkEmbedding, GraphNode, GraphEdge, UserGraphMutation,
        WorkspaceFolder, WorkspaceMember, WorkspaceRole, RcaInsight, QueryHistory
    )
    from app.storage import delete_file as minio_delete
    from pathlib import Path
    from sqlalchemy import delete

    # 0. Break FK cycles before deletions
    await db.execute(delete(RcaInsight).where(RcaInsight.workspace_id == workspace_id))
    await db.execute(delete(QueryHistory).where(QueryHistory.workspace_id == workspace_id))
    # Nullify parent_file_id so we can delete child files freely
    await db.execute(update(File).where(File.workspace_id == workspace_id).values(parent_file_id=None))
    # Nullify AuditLog.file_id FK references upfront
    await db.execute(update(AuditLog).where(AuditLog.workspace_id == workspace_id).values(file_id=None))
    await db.flush()

    # 1. Delete per-file child records, then the file row itself
    files_res = await db.execute(select(File).where(File.workspace_id == workspace_id))
    files = files_res.scalars().all()
    for f in files:
        f_id = f.file_id
        await db.execute(delete(FileComment).where(FileComment.file_id == f_id))
        await db.execute(delete(FileMetadata).where(FileMetadata.file_id == f_id))
        await db.execute(delete(FileAccessOverride).where(FileAccessOverride.file_id == f_id))
        await db.execute(delete(FileEntity).where(FileEntity.file_id == f_id))

        chunks_res = await db.execute(select(FileChunk.chunk_id).where(FileChunk.file_id == f_id))
        c_ids = chunks_res.scalars().all()
        if c_ids:
            await db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(c_ids)))
            await db.execute(delete(FileChunk).where(FileChunk.file_id == f_id))

        try:
            minio_delete(f.storage_key)  # attribute is storage_key, not storage_path
        except Exception:
            pass
        await db.delete(f)

    await db.flush()

    # 2. Delete knowledge graph — edges first (FK on node_id), then nodes, then mutations
    # GraphEdge has no workspace_id; delete via workspace node IDs
    node_ids_res = await db.execute(
        select(GraphNode.node_id).where(GraphNode.workspace_id == workspace_id)
    )
    node_ids = node_ids_res.scalars().all()
    if node_ids:
        await db.execute(
            delete(UserGraphMutation).where(
                UserGraphMutation.from_node_id.in_(node_ids)
            )
        )
        await db.execute(
            delete(UserGraphMutation).where(
                UserGraphMutation.to_node_id.in_(node_ids)
            )
        )
        await db.execute(
            delete(GraphEdge).where(GraphEdge.from_node_id.in_(node_ids))
        )
        await db.execute(
            delete(GraphEdge).where(GraphEdge.to_node_id.in_(node_ids))
        )
        await db.execute(
            delete(GraphNode).where(GraphNode.workspace_id == workspace_id)
        )

    # Also delete any remaining workspace-scoped mutations (workspace_id column exists there)
    await db.execute(delete(UserGraphMutation).where(UserGraphMutation.workspace_id == workspace_id))

    graph_path = Path(f"/backend/data/graphs/{workspace_id}.json")
    if graph_path.exists():
        try:
            graph_path.unlink()
        except Exception:
            pass

    # 3. Delete folders, remaining audit logs, members, roles, and workspace row
    await db.execute(delete(WorkspaceFolder).where(WorkspaceFolder.workspace_id == workspace_id))
    await db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
    await db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id))
    await db.execute(delete(WorkspaceRole).where(WorkspaceRole.workspace_id == workspace_id))

    await db.delete(ws)
    await db.commit()

    return {"detail": f"Workspace '{ws.name}' and all its files, graphs, and data have been permanently hard-deleted."}


# ─── Role Management ──────────────────────────────────────────────────────────

@router.get("/{workspace_id}/roles", response_model=List[RoleOut])
async def list_roles(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all roles in this workspace, ordered by level (highest authority first)."""
    await require_workspace_member(current_user, workspace_id, db)

    roles = await db.execute(
        select(WorkspaceRole)
        .where(WorkspaceRole.workspace_id == workspace_id)
        .order_by(WorkspaceRole.level.asc())
    )
    role_list = roles.scalars().all()

    # Attach member counts
    result = []
    for r in role_list:
        count = await db.scalar(
            select(func.count()).where(WorkspaceMember.role_id == r.role_id)
        )
        result.append(RoleOut(
            role_id=r.role_id,
            workspace_id=r.workspace_id,
            name=r.name,
            level=r.level,
            description=r.description,
            branch=r.branch or "Main",
            parent_role_id=r.parent_role_id,
            member_count=count or 0,
            can_modify_graph=r.can_modify_graph,
            created_at=r.created_at,
        ))
    return result


@router.post("/{workspace_id}/roles", response_model=RoleOut, status_code=201)
async def create_role(
    workspace_id: UUID,
    payload: RoleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new role. Only Level 1 users (highest authority) can manage roles.
    The level number must be unique within this workspace.
    """
    _, _, my_level = await require_workspace_member(current_user, workspace_id, db, max_level=1)

    branch_name = payload.branch or "Main"
    # Check level uniqueness within this branch
    existing_level = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.workspace_id == workspace_id,
            WorkspaceRole.branch == branch_name,
            WorkspaceRole.level == payload.level,
        )
    )
    if existing_level.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"A role with level {payload.level} already exists in branch '{branch_name}'. Choose a different level or branch."
        )

    # Check name uniqueness
    existing_name = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.workspace_id == workspace_id,
            WorkspaceRole.name == payload.name,
        )
    )
    if existing_name.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"A role named '{payload.name}' already exists.")

    role = WorkspaceRole(
        workspace_id=workspace_id,
        name=payload.name,
        level=payload.level,
        description=payload.description,
        branch=branch_name,
        parent_role_id=payload.parent_role_id,
        can_modify_graph=(payload.level == 1 or bool(payload.can_modify_graph)),
    )
    db.add(role)
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="policy_change",
        extra={"type": "role_create", "role_id": str(role.role_id), "name": role.name, "level": role.level, "branch": role.branch}
    ))
    await db.flush()

    return RoleOut(
        role_id=role.role_id,
        workspace_id=role.workspace_id,
        name=role.name,
        level=role.level,
        description=role.description,
        branch=role.branch or "Main",
        parent_role_id=role.parent_role_id,
        member_count=0,
        can_modify_graph=role.can_modify_graph,
        created_at=role.created_at,
    )


@router.patch("/{workspace_id}/roles/{role_id}", response_model=RoleOut)
async def update_role(
    workspace_id: UUID,
    role_id: UUID,
    payload: RoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a role's name or description (not its level — use swap for that)."""
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    result = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.role_id == role_id,
            WorkspaceRole.workspace_id == workspace_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if payload.name:
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description
    if payload.branch is not None:
        # Check collision
        existing_branch_level = await db.execute(
            select(WorkspaceRole).where(
                WorkspaceRole.workspace_id == workspace_id,
                WorkspaceRole.branch == payload.branch,
                WorkspaceRole.level == role.level,
                WorkspaceRole.role_id != role_id,
            )
        )
        if existing_branch_level.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Level {role.level} already taken in branch '{payload.branch}'")
        role.branch = payload.branch
    if payload.parent_role_id is not None:
        role.parent_role_id = payload.parent_role_id
    if payload.can_modify_graph is not None:
        role.can_modify_graph = bool(payload.can_modify_graph) or (role.level == 1)

    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="policy_change",
        extra={"type": "role_update", "role_id": str(role.role_id), "name": role.name, "branch": role.branch}
    ))
    await db.flush()

    count = await db.scalar(select(func.count()).where(WorkspaceMember.role_id == role.role_id))
    return RoleOut(
        role_id=role.role_id,
        workspace_id=role.workspace_id,
        name=role.name,
        level=role.level,
        description=role.description,
        branch=role.branch or "Main",
        parent_role_id=role.parent_role_id,
        member_count=count or 0,
        can_modify_graph=role.can_modify_graph,
        created_at=role.created_at,
    )


@router.delete("/{workspace_id}/roles/{role_id}", status_code=204)
async def delete_role(
    workspace_id: UUID,
    role_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a role. Cannot delete if members are assigned to it.
    Cannot delete the last remaining Level 1 role.
    """
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    result = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.role_id == role_id,
            WorkspaceRole.workspace_id == workspace_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Block deletion if members assigned
    member_count = await db.scalar(
        select(func.count()).where(WorkspaceMember.role_id == role_id)
    )
    if member_count and member_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete role '{role.name}' — {member_count} member(s) are assigned to it. Reassign them first."
        )

    # Block deletion of last Level 1 role
    if role.level == 1:
        l1_count = await db.scalar(
            select(func.count()).where(
                WorkspaceRole.workspace_id == workspace_id,
                WorkspaceRole.level == 1,
            )
        )
        if l1_count and l1_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete the only Level 1 role. At least one Level 1 role must exist."
            )

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="policy_change",
        extra={"type": "role_delete", "role_id": str(role_id), "name": role.name, "level": role.level}
    ))
    await db.delete(role)


@router.post("/{workspace_id}/roles/swap-levels", response_model=List[RoleOut])
async def swap_role_levels(
    workspace_id: UUID,
    payload: SwapLevelsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Swap the level numbers of two roles in this workspace.

    Members remain assigned to their roles by ID — only the level numbers are exchanged.
    This is useful when inserting a new role between existing levels or correcting ordering mistakes.

    Example: Role A (level=2) ↔ Role B (level=5) → Role A becomes level=5, Role B becomes level=2.
    All Role A members now have authority level 5, all Role B members now have authority level 2.
    """
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    # Fetch both roles
    res_a = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.role_id == payload.role_id_a,
            WorkspaceRole.workspace_id == workspace_id,
        )
    )
    role_a = res_a.scalar_one_or_none()

    res_b = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.role_id == payload.role_id_b,
            WorkspaceRole.workspace_id == workspace_id,
        )
    )
    role_b = res_b.scalar_one_or_none()

    if not role_a or not role_b:
        raise HTTPException(status_code=404, detail="One or both roles not found in this workspace")

    if role_a.role_id == role_b.role_id:
        raise HTTPException(status_code=400, detail="Cannot swap a role with itself")

    # Swap levels using a temporary value to avoid unique constraint violation
    TEMP_LEVEL = -1
    level_a, level_b = role_a.level, role_b.level

    role_a.level = TEMP_LEVEL
    await db.flush()
    role_b.level = level_a
    await db.flush()
    role_a.level = level_b
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="policy_change",
        extra={
            "type": "role_swap_levels",
            "role_a_id": str(role_a.role_id),
            "role_a_name": role_a.name,
            "role_a_new_level": role_a.level,
            "role_b_id": str(role_b.role_id),
            "role_b_name": role_b.name,
            "role_b_new_level": role_b.level,
        }
    ))
    await db.flush()

    # Return updated roles with member counts
    result = []
    for role in [role_a, role_b]:
        count = await db.scalar(select(func.count()).where(WorkspaceMember.role_id == role.role_id))
        result.append(RoleOut(
            role_id=role.role_id,
            workspace_id=role.workspace_id,
            name=role.name,
            level=role.level,
            description=role.description,
            branch=role.branch or "Main",
            parent_role_id=role.parent_role_id,
            member_count=count or 0,
            can_modify_graph=role.can_modify_graph,
            created_at=role.created_at,
        ))
    return result


# ─── Member Management ────────────────────────────────────────────────────────

@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=201)
async def invite_member(
    workspace_id: UUID,
    payload: InviteMember,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite a user by email and assign them a role (by role_id). Level 1 only."""
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    # Validate the role belongs to this workspace
    role_res = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.role_id == payload.role_id,
            WorkspaceRole.workspace_id == workspace_id,
        )
    )
    role = role_res.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found in this workspace")

    # Find user by email
    user_res = await db.execute(select(User).where(User.email == payload.email))
    target_user = user_res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found. They must register first.")

    # Check not already a member
    existing = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a workspace member")

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target_user.user_id,
        role_id=payload.role_id,
    )
    db.add(member)
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="member_invite",
        extra={
            "target_user_id": str(target_user.user_id),
            "email": target_user.email,
            "role_id": str(role.role_id),
            "role_name": role.name,
            "role_level": role.level,
        }
    ))
    await db.flush()

    return MemberOut(
        user_id=target_user.user_id,
        email=target_user.email,
        full_name=target_user.full_name,
        role_id=role.role_id,
        role_name=role.name,
        role_level=role.level,
        joined_at=member.joined_at,
    )


@router.patch("/{workspace_id}/members/{user_id}/role", response_model=MemberOut)
async def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRole,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change a member's role. Level 1 only."""
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    # Validate new role
    role_res = await db.execute(
        select(WorkspaceRole).where(
            WorkspaceRole.role_id == payload.role_id,
            WorkspaceRole.workspace_id == workspace_id,
        )
    )
    new_role = role_res.scalar_one_or_none()
    if not new_role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Find member
    mem_res = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.user_id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    row = mem_res.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    member, target_user = row
    member.role_id = payload.role_id
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="policy_change",
        extra={
            "type": "member_role_update",
            "target_user_id": str(target_user.user_id),
            "email": target_user.email,
            "new_role_id": str(new_role.role_id),
            "new_role_name": new_role.name,
            "new_role_level": new_role.level,
        }
    ))
    await db.flush()

    return MemberOut(
        user_id=target_user.user_id,
        email=target_user.email,
        full_name=target_user.full_name,
        role_id=new_role.role_id,
        role_name=new_role.name,
        role_level=new_role.level,
        joined_at=member.joined_at,
    )


@router.get("/{workspace_id}/members", response_model=List[MemberOut])
async def list_members(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_workspace_member(current_user, workspace_id, db)

    result = await db.execute(
        select(WorkspaceMember, User, WorkspaceRole)
        .join(User, User.user_id == WorkspaceMember.user_id)
        .join(WorkspaceRole, WorkspaceRole.role_id == WorkspaceMember.role_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceRole.level.asc(), WorkspaceMember.joined_at)
    )
    rows = result.all()
    return [
        MemberOut(
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
            role_id=role.role_id,
            role_name=role.name,
            role_level=role.level,
            joined_at=member.joined_at,
        )
        for member, user, role in rows
    ]


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the workspace. Level 1 only."""
    await require_workspace_member(current_user, workspace_id, db, max_level=1)

    mem_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = mem_res.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="member_remove",
        extra={"target_user_id": str(user_id)}
    ))
    await db.delete(member)


# ─── Centralized Audit Logs ───────────────────────────────────────────────────

@router.get("/{workspace_id}/audit-logs", response_model=List[AuditLogOut])
async def list_workspace_audit_logs(
    workspace_id: UUID,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Read-only audit history visibility for designated reviewers / workspace members.
    Tracks all governance actions, file access events, and policy changes.
    """
    await require_workspace_member(current_user, workspace_id, db)

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    return result.scalars().all()
