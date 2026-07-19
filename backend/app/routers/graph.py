"""
Graph Router — Industrial Hybrid GraphRAG System

Feature 1: Human-in-the-Loop Knowledge Graph (Shadow Overlay)
  POST /api/v1/graph/edge   — Add a shadow edge to the user overlay
  DELETE /api/v1/graph/edge — Mark a base graph edge as deleted in the overlay

Feature 3: SOPRAG Predictive Agent
  POST /api/v1/graph/rca/trigger — Enqueue an asynchronous RCA analysis task
  GET  /api/v1/graph/rca/{workspace_id} — List insights for a workspace
"""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_workspace_member
from app.database import get_db
from app.models import (
    AuditLog, GraphEdge, GraphMutationAction, GraphNode,
    RcaInsight, User, UserGraphMutation, WorkspaceMember, WorkspaceRole,
)
from app.schemas import (
    AnomalyTrigger, GraphEdgeCreate, GraphEdgeDelete, GraphNodeCreate,
    GraphMutationOut, RcaInsightOut,
)

router = APIRouter(prefix="/graph", tags=["graph"])


# ─── Helper: verify user has can_modify_graph permission ─────────────────────

async def _require_graph_modify_permission(
    current_user: User,
    workspace_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Security gate for Feature 1.
    Queries WorkspaceMember → WorkspaceRole and verifies that the user's role
    has can_modify_graph = True for the given workspace_id.
    Raises HTTP 403 if the permission is not held.
    """
    result = await db.execute(
        select(WorkspaceMember, WorkspaceRole)
        .join(WorkspaceRole, WorkspaceRole.role_id == WorkspaceMember.role_id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.user_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this workspace.",
        )
    _, role = row
    if not role.can_modify_graph and role.level != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Your role '{role.name}' does not have graph modification privileges. "
                "A Level 1 Admin must enable can_modify_graph on your role."
            ),
        )


# ─── Resolve node helper ──────────────────────────────────────────────────────

async def _get_node_or_404(node_id: UUID, db: AsyncSession) -> GraphNode:
    res = await db.execute(select(GraphNode).where(GraphNode.node_id == node_id))
    node = res.scalar_one_or_none()
    if not node:
        raise HTTPException(
            status_code=404,
            detail=f"Graph node {node_id} not found.",
        )
    return node


# ─── Custom Node Management Endpoints ────────────────────────────────────────

@router.post("/node", status_code=201)
async def add_graph_node(
    payload: GraphNodeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a custom node (e.g. concept, equipment tag, asset) to the knowledge graph."""
    await _require_graph_modify_permission(current_user, payload.workspace_id, db)

    ext_id = payload.label.strip().upper()
    existing = await db.execute(
        select(GraphNode).where(
            GraphNode.workspace_id == payload.workspace_id,
            GraphNode.external_id == ext_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"A node with external ID/label '{ext_id}' already exists in this workspace.")

    props = payload.properties or {}
    props["branch"] = payload.branch or "Entities"
    props["custom_created_by"] = str(current_user.user_id)

    node = GraphNode(
        workspace_id=payload.workspace_id,
        node_type=payload.node_type or "entity",
        external_id=ext_id,
        label=payload.label.strip(),
        properties=props,
    )
    db.add(node)
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=payload.workspace_id,
        action="graph_node_add",
        extra={"node_id": str(node.node_id), "label": node.label, "type": node.node_type},
    ))
    await db.commit()
    return {
        "node_id": str(node.node_id),
        "workspace_id": str(node.workspace_id),
        "label": node.label,
        "node_type": node.node_type,
        "external_id": node.external_id,
        "properties": node.properties,
    }


@router.delete("/node/{node_id}", status_code=200)
async def delete_graph_node(
    node_id: UUID,
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom or entity node from the knowledge graph and all its incident edges."""
    await _require_graph_modify_permission(current_user, workspace_id, db)

    result = await db.execute(
        select(GraphNode).where(GraphNode.node_id == node_id, GraphNode.workspace_id == workspace_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    from sqlalchemy import or_
    await db.execute(
        GraphEdge.__table__.delete().where(
            or_(GraphEdge.from_node_id == node_id, GraphEdge.to_node_id == node_id)
        )
    )
    await db.execute(
        UserGraphMutation.__table__.delete().where(
            or_(UserGraphMutation.from_node_id == node_id, UserGraphMutation.to_node_id == node_id)
        )
    )
    await db.delete(node)

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        action="graph_node_delete",
        extra={"node_id": str(node_id), "label": node.label},
    ))
    await db.commit()
    return {"detail": f"Node '{node.label}' and all connected edges deleted."}


# ─── Feature 1: Shadow Overlay Endpoints ─────────────────────────────────────

@router.post("/edge", response_model=GraphMutationOut, status_code=201)
async def add_shadow_edge(
    payload: GraphEdgeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a virtual edge to the user shadow overlay.

    The base graph_edges table is NOT modified. Instead, an ADD record is written
    to user_graph_mutations. The retrieval engine will include this edge (with the
    specified weight boosting the similarity score) during graph_search.

    Security gate: user's WorkspaceRole must have can_modify_graph = True.
    """
    await _require_graph_modify_permission(current_user, payload.workspace_id, db)

    # Validate both nodes exist
    await _get_node_or_404(payload.from_node_id, db)
    await _get_node_or_404(payload.to_node_id, db)

    # Prevent duplicate ADD mutations
    existing = await db.execute(
        select(UserGraphMutation).where(
            UserGraphMutation.workspace_id == payload.workspace_id,
            UserGraphMutation.from_node_id == payload.from_node_id,
            UserGraphMutation.to_node_id == payload.to_node_id,
            UserGraphMutation.action == GraphMutationAction.ADD,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="An ADD shadow edge between these nodes already exists in this workspace.",
        )

    mutation = UserGraphMutation(
        workspace_id=payload.workspace_id,
        from_node_id=payload.from_node_id,
        to_node_id=payload.to_node_id,
        action=GraphMutationAction.ADD,
        label=payload.label,
        comment=payload.comment,
        weight=payload.weight,
        created_by_user_id=current_user.user_id,
    )
    db.add(mutation)
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=payload.workspace_id,
        action="graph_edge_add",
        extra={
            "mutation_id": str(mutation.mutation_id),
            "from_node_id": str(payload.from_node_id),
            "to_node_id": str(payload.to_node_id),
            "label": payload.label,
            "weight": payload.weight,
        },
    ))

    await db.commit()
    return mutation


@router.delete("/edge", status_code=200)
async def delete_shadow_edge(
    payload: GraphEdgeDelete,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a base graph edge as deleted in the shadow overlay.

    A DELETE record is written to user_graph_mutations. The retrieval engine will
    exclude any base graph_edges matching this from/to pair for this workspace.
    The base graph_edges table is NOT modified.

    Security gate: user's WorkspaceRole must have can_modify_graph = True.
    """
    await _require_graph_modify_permission(current_user, payload.workspace_id, db)

    # Validate both nodes exist
    await _get_node_or_404(payload.from_node_id, db)
    await _get_node_or_404(payload.to_node_id, db)

    # Prevent duplicate DELETE mutations
    existing = await db.execute(
        select(UserGraphMutation).where(
            UserGraphMutation.workspace_id == payload.workspace_id,
            UserGraphMutation.from_node_id == payload.from_node_id,
            UserGraphMutation.to_node_id == payload.to_node_id,
            UserGraphMutation.action == GraphMutationAction.DELETE,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="A DELETE shadow override for this edge already exists in this workspace.",
        )

    mutation = UserGraphMutation(
        workspace_id=payload.workspace_id,
        from_node_id=payload.from_node_id,
        to_node_id=payload.to_node_id,
        action=GraphMutationAction.DELETE,
        weight=0.0,  # weight has no meaning for DELETE actions
        created_by_user_id=current_user.user_id,
    )
    db.add(mutation)
    await db.flush()

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=payload.workspace_id,
        action="graph_edge_delete",
        extra={
            "mutation_id": str(mutation.mutation_id),
            "from_node_id": str(payload.from_node_id),
            "to_node_id": str(payload.to_node_id),
        },
    ))

    await db.commit()
    return {"detail": "Shadow DELETE override recorded. The edge will be excluded from retrieval."}


@router.delete("/mutations/{mutation_id}", status_code=200)
async def delete_user_mutation(
    mutation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a user-created shadow mutation (ADD or DELETE override).
    Only the creator can remove their own mutation.
    """
    result = await db.execute(
        select(UserGraphMutation).where(UserGraphMutation.mutation_id == mutation_id)
    )
    mutation = result.scalar_one_or_none()
    if not mutation:
        raise HTTPException(status_code=404, detail="Mutation not found.")
    if mutation.created_by_user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own mutations.")

    await db.delete(mutation)
    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=mutation.workspace_id,
        action="graph_mutation_removed",
        extra={"mutation_id": str(mutation_id)},
    ))
    await db.commit()
    return {"detail": "Mutation removed."}


@router.get("/mutations/{workspace_id}", response_model=List[GraphMutationOut])
async def list_graph_mutations(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all shadow overlay mutations for a workspace (requires workspace membership)."""
    await require_workspace_member(current_user, workspace_id, db)

    result = await db.execute(
        select(UserGraphMutation)
        .where(UserGraphMutation.workspace_id == workspace_id)
        .order_by(UserGraphMutation.created_at.desc())
    )
    return result.scalars().all()


# ─── Feature 3: SOPRAG RCA Agent Endpoints ───────────────────────────────────

@router.post("/rca/trigger", status_code=202)
async def trigger_rca_analysis(
    payload: AnomalyTrigger,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Feature 3 — Trigger SOPRAG Predictive RCA Agent.

    Enqueues an asynchronous Celery task that:
      1. Runs 3-view SOPRAG retrieval (entity / causal / flow graph queries)
      2. Calls Groq LLM with the counterfactual-reasoning persona prompt
      3. Parses the structured JSON response and persists it to rca_insights

    Returns 202 Accepted with the task ID. Poll GET /rca/{workspace_id} for results.
    """
    await require_workspace_member(current_user, payload.workspace_id, db)

    # Import here to avoid circular imports at module load time
    from app.workers.rca_agent import analyze_anomaly_task

    task = analyze_anomaly_task.delay(
        str(payload.workspace_id),
        payload.asset_id,
        payload.anomaly_data,
    )

    db.add(AuditLog(
        user_id=current_user.user_id,
        workspace_id=payload.workspace_id,
        action="rca_trigger",
        extra={
            "asset_id": payload.asset_id,
            "celery_task_id": task.id,
        },
    ))

    return {
        "detail": "RCA analysis task enqueued successfully.",
        "task_id": task.id,
        "asset_id": payload.asset_id,
        "workspace_id": str(payload.workspace_id),
    }


@router.get("/rca/{workspace_id}", response_model=List[RcaInsightOut])
async def list_rca_insights(
    workspace_id: UUID,
    asset_id: str = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List RCA insights for a workspace.
    Optionally filter by asset_id. Results ordered by most recent first.
    """
    await require_workspace_member(current_user, workspace_id, db)

    q = (
        select(RcaInsight)
        .where(RcaInsight.workspace_id == workspace_id)
        .order_by(RcaInsight.created_at.desc())
        .limit(limit)
    )
    if asset_id:
        q = q.where(RcaInsight.asset_id == asset_id)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/workspace/{workspace_id}")
async def get_workspace_graph(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch the knowledge graph for a workspace — file nodes only,
    each colored by their branch (folder name), with both system
    edges (SUPERSEDED_BY) and user-created edges (ADD mutations).
    """
    await require_workspace_member(current_user, workspace_id, db)

    # Fetch file, asset, and entity nodes for the workspace graph
    nodes_result = await db.execute(
        select(GraphNode).where(
            GraphNode.workspace_id == workspace_id,
            GraphNode.node_type.in_(["file", "asset", "entity"]),
        ).limit(1000)
    )
    nodes = nodes_result.scalars().all()
    node_ids = [n.node_id for n in nodes]

    # Base system edges (SUPERSEDED_BY, SIMILAR_TO, BELONGS_TO_ASSET, MENTIONS, RELATED_TO)
    system_edges = []
    if node_ids:
        edges_result = await db.execute(
            select(GraphEdge).where(
                GraphEdge.from_node_id.in_(node_ids),
                GraphEdge.to_node_id.in_(node_ids),
            ).limit(2000)
        )
        system_edges = edges_result.scalars().all()

    # User shadow mutations (ADD and DELETE) for this workspace
    mutations_result = await db.execute(
        select(UserGraphMutation)
        .where(UserGraphMutation.workspace_id == workspace_id)
        .order_by(UserGraphMutation.created_at.desc())
    )
    mutations = mutations_result.scalars().all()

    # Build SET of deleted edge pairs for filtering
    deleted_pairs = {
        (str(m.from_node_id), str(m.to_node_id))
        for m in mutations
        if m.action == GraphMutationAction.DELETE
    }

    # Filter system edges to remove shadow-deleted ones
    visible_system_edges = [
        e for e in system_edges
        if (str(e.from_node_id), str(e.to_node_id)) not in deleted_pairs
    ]

    return {
        "nodes": [
            {
                "id": str(n.node_id),
                "name": n.label,
                "val": 2.0 if n.node_type == "file" else 1.2,
                "group": n.node_type,
                "branch": (n.properties or {}).get("branch", "Asset" if n.node_type == "asset" else ("Entity" if n.node_type == "entity" else "Root")),
                "file_family": (n.properties or {}).get("file_family", ""),
                "status": (n.properties or {}).get("status", ""),
                "external_id": n.external_id,
            }
            for n in nodes
        ],
        "links": [
            *[
                {
                    "id": str(e.edge_id),
                    "source": str(e.from_node_id),
                    "target": str(e.to_node_id),
                    "name": e.edge_type,
                    "edge_source": "system",
                    "weight": e.weight,
                }
                for e in visible_system_edges
            ],
            *[
                {
                    "id": str(m.mutation_id),
                    "source": str(m.from_node_id),
                    "target": str(m.to_node_id),
                    "name": m.label or "related",
                    "comment": m.comment or "",
                    "edge_source": "user",
                    "weight": m.weight,
                    "created_by": str(m.created_by_user_id),
                }
                for m in mutations
                if m.action == GraphMutationAction.ADD
            ],
        ],
        "mutations": [
            {
                "mutation_id": str(m.mutation_id),
                "from_node_id": str(m.from_node_id),
                "to_node_id": str(m.to_node_id),
                "action": m.action.value if hasattr(m.action, 'value') else str(m.action),
                "label": m.label,
                "comment": m.comment,
                "weight": m.weight,
                "created_by_user_id": str(m.created_by_user_id),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in mutations
        ],
    }
