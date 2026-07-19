"""Maintenance Calendar Agent — RAC Calendar Phase

Implements document upload extraction and natural language query processing for
equipment maintenance schedules, intervals, and rituals according to prompt4calendar.md.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import structlog
from app.config import settings

logger = structlog.get_logger()

CALENDAR_SYSTEM_PROMPT = """You are an AI agent embedded in an industrial knowledge system.
Your sole responsibility in this phase is to manage a maintenance calendar for equipment, based on:
- Uploaded documents (manuals, SOPs, schedules, incident reports).
- User queries/commands.

You must produce structured events with exact fields:
- title: Short, human-readable name (e.g., "Quarterly inspection – Pump P-101").
- equipment_id: Identifier or tag for the equipment (if known, e.g. "P-101").
- workspace_id: Logical workspace/tenant this event belongs to.
- event_type: One of: "preventive", "shutdown", "inspection", "calibration", "test", "other".
- start_at: ISO 8601 datetime (e.g., "2026-09-30T08:00:00Z"). If date is unspecified, estimate or use current/upcoming date.
- end_at: ISO 8601 datetime, or null if not specified.
- repeat_rule: Simple recurrence rule or null (e.g., "every 3 months", "every year", "monthly").
- description: Short explanation, including references to source sections/pages.
- source_type: One of: "document", "query", "manual".
- source_id: Identifier for the source document or query (string provided in input).
- confidence: "high", "medium", or "low".

Rules:
1. Only create events that clearly relate to maintenance, inspection, calibration, or equipment-related schedules.
2. Do not duplicate identical events from different sections of the same document.
3. You MUST respond with pure JSON containing ONLY an array of event objects, like this:
[
  {
    "title": "Quarterly inspection – Pump P-101",
    "equipment_id": "P-101",
    "workspace_id": "workspace-123",
    "event_type": "inspection",
    "start_at": "2026-09-30T08:00:00Z",
    "end_at": null,
    "repeat_rule": "every 3 months",
    "description": "Derived from Maintenance Manual: 'Inspect Pump P-101 every three months.'",
    "source_type": "document",
    "source_id": "doc-123",
    "confidence": "high"
  }
]
If there are no calendar-worthy events, output: []
"""


def _strip_null_bytes(data: Any) -> Any:
    if isinstance(data, str):
        return data.replace("\x00", "")
    elif isinstance(data, dict):
        return {k: _strip_null_bytes(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_strip_null_bytes(item) for item in data]
    return data


async def _call_llm_json(prompt: str) -> Optional[List[Dict[str, Any]]]:
    """Call Groq or OpenAI for JSON array output."""
    messages = [
        {"role": "system", "content": CALENDAR_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        if settings.GROQ_API_KEY:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json={
                        "model": settings.GROQ_CHAT_MODEL,
                        "messages": messages,
                        "temperature": 0.1,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content_str = data["choices"][0]["message"]["content"].strip()
                    # Extract JSON array from markdown/text if needed
                    match = re.search(r'\[.*\]', content_str, re.DOTALL)
                    if match:
                        return json.loads(match.group(0))
        elif settings.OPENAI_API_KEY:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "temperature": 0.1,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content_str = data["choices"][0]["message"]["content"].strip()
                    match = re.search(r'\[.*\]', content_str, re.DOTALL)
                    if match:
                        return json.loads(match.group(0))
    except Exception as exc:
        logger.warning("calendar_agent_llm_error", error=str(exc))
    return None


def _fallback_rule_extract(
    text: str,
    source_type: str,
    source_id: str,
    workspace_id: UUID,
    equipment_tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Deterministic rule/regex based fallback when LLM is unavailable."""
    events = []
    text_clean = text.replace("\x00", "")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Find intervals like "every X months/weeks/days/years" or "monthly", "quarterly", "annual"
    intervals = [
        (r'\bevery\s+(\d+)\s+(month|year|week|day)s?\b', "every {0} {1}s"),
        (r'\b(monthly)\b', "every month"),
        (r'\b(quarterly)\b', "every 3 months"),
        (r'\b(annually|yearly|annual)\b', "every year"),
        (r'\b(weekly)\b', "every week"),
    ]

    event_type_keywords = {
        "calibration": "calibration",
        "shutdown": "shutdown",
        "inspection": "inspection",
        "test": "test",
        "preventive": "preventive",
        "maintenance": "preventive",
        "lubricate": "preventive",
        "check": "inspection",
        "analyze": "inspection",
        "analysis": "inspection",
    }

    # Extract tags from text or input list
    equip_pattern = re.compile(r'\b([A-Z]{1,3}-?\d{3,6}[A-Z]?)\b')
    found_tags = list(set(equip_pattern.findall(text_clean.upper())))
    if equipment_tags:
        found_tags.extend(equipment_tags)
    found_tags = list(set([t for t in found_tags if len(t) >= 2]))

    # Split into paragraphs or sentences to find schedules
    paragraphs = [p.strip() for p in re.split(r'[\r\n\.\?]', text_clean) if len(p.strip()) > 15]

    for p in paragraphs:
        p_lower = p.lower()
        matched_rule = None
        for pattern, rule_template in intervals:
            match = re.search(pattern, p_lower, re.IGNORECASE)
            if match:
                if "{0}" in rule_template:
                    matched_rule = rule_template.format(match.group(1), match.group(2))
                else:
                    matched_rule = rule_template
                break

        # Also check for date mentions like "June 15" or ISO dates
        date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', p)
        start_date = date_match.group(1) + "T08:00:00Z" if date_match else now_iso

        # If interval or date mention or strong maintenance keyword with tag found
        matched_type = None
        for kw, etype in event_type_keywords.items():
            if kw in p_lower:
                matched_type = etype
                break

        if matched_rule or (matched_type and found_tags) or date_match:
            e_type = matched_type or "preventive"
            # Find equipment tag closest or in paragraph
            e_id = None
            for t in found_tags:
                if t.lower() in p_lower:
                    e_id = t
                    break
            if not e_id and found_tags:
                e_id = found_tags[0]

            title_prefix = e_type.capitalize()
            title = f"{title_prefix} – {e_id}" if e_id else f"{title_prefix} task"
            if len(p) < 60:
                title = p.strip().capitalize()[:120]

            events.append({
                "title": title[:512],
                "equipment_id": e_id,
                "workspace_id": str(workspace_id),
                "event_type": e_type,
                "start_at": start_date,
                "end_at": None,
                "repeat_rule": matched_rule,
                "description": f"Extracted from {source_type}: '{p[:300]}'",
                "source_type": source_type,
                "source_id": str(source_id),
                "confidence": "medium" if matched_rule else "low",
            })

    # Deduplicate events by title + equipment_id + repeat_rule
    dedup = {}
    for ev in events:
        key = (ev["title"], ev.get("equipment_id"), ev.get("repeat_rule"))
        if key not in dedup:
            dedup[key] = ev
    return _strip_null_bytes(list(dedup.values())[:30])  # limit max events per scan


async def extract_events_from_document(
    text: str,
    document_id: str,
    workspace_id: UUID,
    equipment_tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Extract maintenance calendar events from document text on upload."""
    if not text or len(text.strip()) < 20:
        return []

    # Prepare prompt with first ~12000 chars and equipment context
    sample_text = text[:12000].replace("\x00", "")
    equip_context = f"Known equipment tags in document: {', '.join(equipment_tags)}" if equipment_tags else ""
    
    prompt = f"""Document ID: {document_id}
Workspace ID: {workspace_id}
{equip_context}

Document Content:
{sample_text}

Extract all maintenance schedules, inspection dates, calibration intervals, or shutdowns as structured JSON events."""

    llm_events = await _call_llm_json(prompt)
    if llm_events is not None and isinstance(llm_events, list):
        # Validate and sanitize required fields
        cleaned = []
        for ev in llm_events:
            if not isinstance(ev, dict) or not ev.get("title"):
                continue
            ev["workspace_id"] = str(workspace_id)
            ev["source_type"] = "document"
            ev["source_id"] = str(document_id)
            if not ev.get("start_at"):
                ev["start_at"] = datetime.now(timezone.utc).isoformat()
            if not ev.get("confidence"):
                ev["confidence"] = "high"
            if not ev.get("event_type"):
                ev["event_type"] = "preventive"
            cleaned.append(ev)
        return _strip_null_bytes(cleaned[:50])

    # Fallback to rule extraction
    return _fallback_rule_extract(text, "document", str(document_id), workspace_id, equipment_tags)


async def parse_calendar_query(
    query_text: str,
    workspace_id: UUID,
    query_id: str,
) -> List[Dict[str, Any]]:
    """Interpret natural language commands into maintenance calendar events."""
    prompt = f"""User Command: "{query_text}"
Workspace ID: {workspace_id}
Query ID: {query_id}

Interpret this query and construct the maintenance calendar event(s) requested.
If the query is only informational ("show me events"), output: []"""

    llm_events = await _call_llm_json(prompt)
    if llm_events is not None and isinstance(llm_events, list):
        cleaned = []
        for ev in llm_events:
            if not isinstance(ev, dict) or not ev.get("title"):
                continue
            ev["workspace_id"] = str(workspace_id)
            ev["source_type"] = "query"
            ev["source_id"] = str(query_id)
            if not ev.get("start_at"):
                ev["start_at"] = datetime.now(timezone.utc).isoformat()
            if not ev.get("confidence"):
                ev["confidence"] = "high"
            cleaned.append(ev)
        return _strip_null_bytes(cleaned)

    # Fallback rule extraction for query
    return _fallback_rule_extract(query_text, "query", str(query_id), workspace_id)
