"""Calendar Router — RAC Maintenance Calendar API endpoints

Provides query, management, and recurrence expansion for equipment maintenance schedules.
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    MaintenanceEvent,
    GraphNode,
    GraphEdge,
    User,
    WorkspaceMember,
)
from app.routers.auth import get_current_user
from app.schemas import (
    CalendarQueryRequest,
    MaintenanceEventCreate,
    MaintenanceEventOut,
    MaintenanceEventUpdate,
)
from app.services.calendar_agent import parse_calendar_query

logger = structlog.get_logger()
router = APIRouter(prefix="/workspaces/{workspace_id}/calendar", tags=["calendar"])


def _verify_workspace_access(db: Session, workspace_id: UUID, user: User) -> WorkspaceMember:
    member = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.user_id,
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    return member


@router.get("/events", response_model=List[MaintenanceEventOut])
async def list_calendar_events(
    workspace_id: UUID,
    equipment_id: Optional[str] = Query(None, description="Filter by asset/tag e.g. P-101"),
    event_type: Optional[str] = Query(None, description="preventive, shutdown, inspection, calibration, test, other"),
    source_type: Optional[str] = Query(None, description="document, query, manual"),
    start_after: Optional[datetime] = Query(None),
    end_before: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List maintenance calendar events for the workspace."""
    _verify_workspace_access(db, workspace_id, current_user)

    stmt = select(MaintenanceEvent).where(MaintenanceEvent.workspace_id == workspace_id)
    if equipment_id:
        stmt = stmt.where(MaintenanceEvent.equipment_id == equipment_id)
    if event_type:
        stmt = stmt.where(MaintenanceEvent.event_type == event_type)
    if source_type:
        stmt = stmt.where(MaintenanceEvent.source_type == source_type)
    if start_after:
        stmt = stmt.where(MaintenanceEvent.start_at >= start_after)
    if end_before:
        stmt = stmt.where(MaintenanceEvent.start_at <= end_before)

    stmt = stmt.order_by(MaintenanceEvent.start_at.asc())
    events = db.execute(stmt).scalars().all()
    return events


@router.get("/events/expanded", response_model=List[Dict[str, Any]])
async def list_expanded_calendar_events(
    workspace_id: UUID,
    months: int = Query(6, ge=1, le=24, description="Months into the future to expand recurrence rules"),
    equipment_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List maintenance events with recurrence rules expanded into concrete future date instances for UIs."""
    _verify_workspace_access(db, workspace_id, current_user)

    stmt = select(MaintenanceEvent).where(MaintenanceEvent.workspace_id == workspace_id)
    if equipment_id:
        stmt = stmt.where(MaintenanceEvent.equipment_id == equipment_id)
    events = db.execute(stmt).scalars().all()

    expanded = []
    now = datetime.now(timezone.utc)
    limit_dt = now + timedelta(days=30 * months)

    for ev in events:
        base_dict = {
            "event_id": str(ev.event_id),
            "workspace_id": str(ev.workspace_id),
            "title": ev.title,
            "equipment_id": ev.equipment_id,
            "event_type": ev.event_type,
            "start_at": ev.start_at.isoformat() if ev.start_at else now.isoformat(),
            "end_at": ev.end_at.isoformat() if ev.end_at else None,
            "repeat_rule": ev.repeat_rule,
            "description": ev.description,
            "source_type": ev.source_type,
            "source_id": ev.source_id,
            "confidence": ev.confidence,
            "is_expanded_instance": False,
        }
        expanded.append(base_dict)

        # Expand recurrence if present
        if ev.repeat_rule and ev.start_at:
            rule_lower = ev.repeat_rule.lower()
            interval_days = 0
            if "month" in rule_lower:
                # e.g. "every month" or "every 3 months"
                num = 1
                for w in rule_lower.split():
                    if w.isdigit():
                        num = int(w)
                        break
                interval_days = 30 * num
            elif "week" in rule_lower:
                num = 1
                for w in rule_lower.split():
                    if w.isdigit():
                        num = int(w)
                        break
                interval_days = 7 * num
            elif "year" in rule_lower or "annual" in rule_lower:
                num = 1
                for w in rule_lower.split():
                    if w.isdigit():
                        num = int(w)
                        break
                interval_days = 365 * num
            elif "day" in rule_lower:
                num = 1
                for w in rule_lower.split():
                    if w.isdigit():
                        num = int(w)
                        break
                interval_days = num

            if interval_days > 0:
                curr_dt = ev.start_at + timedelta(days=interval_days)
                instance_count = 1
                while curr_dt <= limit_dt and instance_count < 24:
                    inst_dict = dict(base_dict)
                    inst_dict["start_at"] = curr_dt.isoformat()
                    inst_dict["is_expanded_instance"] = True
                    inst_dict["instance_number"] = instance_count
                    expanded.append(inst_dict)
                    curr_dt += timedelta(days=interval_days)
                    instance_count += 1

    # Sort expanded by date
    expanded.sort(key=lambda x: x.get("start_at", ""))
    return expanded


@router.post("/events", response_model=MaintenanceEventOut, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    workspace_id: UUID,
    payload: MaintenanceEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually create a maintenance calendar event and link to Knowledge Graph."""
    _verify_workspace_access(db, workspace_id, current_user)

    event = MaintenanceEvent(
        workspace_id=workspace_id,
        title=payload.title,
        equipment_id=payload.equipment_id,
        event_type=payload.event_type,
        start_at=payload.start_at or datetime.now(timezone.utc),
        end_at=payload.end_at,
        repeat_rule=payload.repeat_rule,
        description=payload.description,
        source_type=payload.source_type,
        source_id=payload.source_id,
        confidence=payload.confidence,
    )
    db.add(event)
    db.flush()

    # Create event node in KG
    ev_node = GraphNode(
        node_type="event",
        external_id=str(event.event_id),
        workspace_id=workspace_id,
        label=event.title[:255],
        properties={
            "event_type": event.event_type,
            "repeat_rule": event.repeat_rule,
            "start_at": event.start_at.isoformat() if event.start_at else None,
            "branch": "Schedules",
        },
    )
    db.add(ev_node)
    db.flush()

    if event.equipment_id:
        asset_node = db.execute(
            select(GraphNode).where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.external_id == event.equipment_id.upper(),
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
    db.refresh(event)
    return event


@router.post("/query", response_model=List[MaintenanceEventOut])
async def execute_calendar_query(
    workspace_id: UUID,
    payload: CalendarQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute natural language calendar commands (e.g. 'Add monthly vibration analysis for compressor C-17')."""
    _verify_workspace_access(db, workspace_id, current_user)

    query_id_str = payload.query_id or f"q-{uuid.uuid4()}"
    extracted = await parse_calendar_query(payload.query, workspace_id, query_id_str)

    created_events = []
    for ev in extracted:
        start_dt = None
        if ev.get("start_at"):
            try:
                start_dt = datetime.fromisoformat(str(ev["start_at"]).replace("Z", "+00:00"))
            except Exception:
                start_dt = datetime.now(timezone.utc)

        m_ev = MaintenanceEvent(
            workspace_id=workspace_id,
            title=str(ev.get("title", "Command Task"))[:512],
            equipment_id=str(ev.get("equipment_id", "")[:256]) if ev.get("equipment_id") else None,
            event_type=str(ev.get("event_type", "preventive"))[:64],
            start_at=start_dt,
            end_at=None,
            repeat_rule=str(ev.get("repeat_rule", ""))[:256] if ev.get("repeat_rule") else None,
            description=str(ev.get("description", ""))[:2000],
            source_type="query",
            source_id=query_id_str,
            confidence=str(ev.get("confidence", "high"))[:32],
        )
        db.add(m_ev)
        db.flush()

        # KG node
        ev_node = GraphNode(
            node_type="event",
            external_id=str(m_ev.event_id),
            workspace_id=workspace_id,
            label=m_ev.title[:255],
            properties={
                "event_type": m_ev.event_type,
                "repeat_rule": m_ev.repeat_rule,
                "start_at": m_ev.start_at.isoformat() if m_ev.start_at else None,
                "branch": "Schedules",
            },
        )
        db.add(ev_node)
        db.flush()

        if m_ev.equipment_id:
            asset_node = db.execute(
                select(GraphNode).where(
                    GraphNode.workspace_id == workspace_id,
                    GraphNode.external_id == m_ev.equipment_id.upper(),
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

        created_events.append(m_ev)

    db.commit()
    for ev in created_events:
        db.refresh(ev)
    return created_events


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_event(
    workspace_id: UUID,
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a maintenance calendar event and its associated Knowledge Graph node."""
    _verify_workspace_access(db, workspace_id, current_user)

    event = db.execute(
        select(MaintenanceEvent).where(
            MaintenanceEvent.workspace_id == workspace_id,
            MaintenanceEvent.event_id == event_id,
        )
    ).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Delete KG node and edges
    node = db.execute(
        select(GraphNode).where(
            GraphNode.workspace_id == workspace_id,
            GraphNode.node_type == "event",
            GraphNode.external_id == str(event_id),
        )
    ).scalar_one_or_none()
    if node:
        db.execute(GraphEdge.__table__.delete().where(
            (GraphEdge.from_node_id == node.node_id) | (GraphEdge.to_node_id == node.node_id)
        ))
        db.delete(node)

    db.delete(event)
    db.commit()
