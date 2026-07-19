"""
SOPRAG Predictive RCA Agent — Celery Worker (Feature 3)

Implements Multi-view Graph Experts Retrieval (SOPRAG) for Root Cause Analysis:
  View 1: Entity Graph Query  — physical asset + connected components
  View 2: Causal Graph Query  — historical failure logs + user shadow connections
  View 3: Flow Graph Query    — compliance namespace vector search (OSHA, ASME, etc.)

The worker assembles multi-view context, calls the Groq LLM with a rigid
Counterfactual Reasoning Persona prompt, parses the structured JSON response,
and persists the result to the rca_insights table.

Required env vars:
  GROQ_API_KEY        — Groq LLM API key
  GROQ_RCA_MODEL      — Model to use (default: llama-3.3-70b-versatile)
  OPENAI_API_KEY      — Used for compliance namespace vector embeddings
"""
import json
import logging
import uuid
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ─── Synchronous DB session for Celery tasks ──────────────────────────────────

def _get_sync_session() -> Session:
    """Create a synchronous SQLAlchemy session for use inside Celery tasks."""
    engine = create_engine(settings.CELERY_DATABASE_URL)
    return Session(engine)


# ─── SOPRAG Multi-View Retrieval ──────────────────────────────────────────────

def _entity_graph_query(db: Session, workspace_id: str, asset_id: str) -> str:
    """
    View 1 — Entity Graph Query.
    Fetches physical asset details and all directly connected components
    from graph_nodes and graph_edges. Includes user-added shadow ADD edges
    from user_graph_mutations so human-curated knowledge is included.
    """
    rows = db.execute(
        text("""
            -- Base asset node details
            SELECT
                gn_asset.node_id,
                gn_asset.node_type,
                gn_asset.label,
                gn_asset.properties,
                gn_connected.label AS connected_label,
                gn_connected.node_type AS connected_type,
                ge.edge_type,
                ge.weight AS edge_weight,
                'base' AS source
            FROM graph_nodes gn_asset
            LEFT JOIN graph_edges ge ON ge.from_node_id = gn_asset.node_id
            LEFT JOIN graph_nodes gn_connected ON gn_connected.node_id = ge.to_node_id
            WHERE gn_asset.node_type = 'asset'
              AND gn_asset.label = :asset_id
              AND (gn_asset.workspace_id = CAST(:wid AS uuid) OR gn_asset.workspace_id IS NULL)
              -- Exclude edges overridden as DELETE in the shadow overlay
              AND NOT EXISTS (
                  SELECT 1 FROM user_graph_mutations ugm
                  WHERE ugm.workspace_id = CAST(:wid AS uuid)
                    AND ugm.action = 'DELETE'
                    AND ugm.from_node_id = ge.from_node_id
                    AND ugm.to_node_id = ge.to_node_id
              )

            UNION ALL

            -- Shadow ADD connections from the human overlay
            SELECT
                ugm.from_node_id AS node_id,
                gn_from.node_type,
                gn_from.label,
                gn_from.properties,
                gn_to.label AS connected_label,
                gn_to.node_type AS connected_type,
                'USER_SHADOW_ADD' AS edge_type,
                ugm.weight AS edge_weight,
                'shadow' AS source
            FROM user_graph_mutations ugm
            JOIN graph_nodes gn_from ON gn_from.node_id = ugm.from_node_id
            JOIN graph_nodes gn_to   ON gn_to.node_id   = ugm.to_node_id
            WHERE ugm.workspace_id = CAST(:wid AS uuid)
              AND ugm.action = 'ADD'
              AND gn_from.label = :asset_id

            LIMIT 50
        """),
        {"asset_id": asset_id, "wid": workspace_id},
    ).fetchall()

    if not rows:
        return f"No entity graph data found for asset '{asset_id}'."

    lines = [f"ENTITY GRAPH — Asset: {asset_id}"]
    for row in rows:
        lines.append(
            f"  [{row.source}] {row.label} ({row.node_type}) "
            f"--[{row.edge_type}, w={row.edge_weight}]--> "
            f"{row.connected_label or 'N/A'} ({row.connected_type or 'N/A'})"
        )
    return "\n".join(lines)


def _causal_graph_query(db: Session, workspace_id: str, asset_id: str) -> str:
    """
    View 2 — Causal Graph Query.
    Retrieves historical failure log chunks and file entities related to the asset,
    combined with user-defined shadow ADD connections from Feature 1.
    """
    rows = db.execute(
        text("""
            SELECT DISTINCT
                f.original_name,
                f.title,
                fc.content,
                fc.chunk_type,
                f.upload_ts
            FROM file_entities fe
            JOIN files f ON f.file_id = fe.file_id
            JOIN file_chunks fc ON fc.file_id = f.file_id
            WHERE f.workspace_id = CAST(:wid AS uuid)
              AND f.processing_status = 'done'
              AND fe.entity_type IN ('equipment', 'asset', 'work_order')
              AND (fe.entity_value ILIKE :asset_pattern OR f.title ILIKE :asset_pattern)
            ORDER BY f.upload_ts DESC
            LIMIT 20
        """),
        {"wid": workspace_id, "asset_pattern": f"%{asset_id}%"},
    ).fetchall()

    if not rows:
        return f"No historical failure logs found for asset '{asset_id}'."

    lines = [f"CAUSAL GRAPH — Historical Failure Logs for: {asset_id}"]
    for row in rows:
        lines.append(
            f"\n  [{row.upload_ts.date() if row.upload_ts else 'unknown'}] "
            f"{row.title or row.original_name} ({row.chunk_type}):\n"
            f"  {row.content[:400]}..."
        )
    return "\n".join(lines)


def _flow_graph_query(
    db: Session,
    workspace_id: str,
    anomaly_data: Dict[str, Any],
    asset_id: str,
) -> str:
    """
    View 3 — Flow Graph Query (Compliance Namespace).
    Performs a vector similarity search against chunks tagged as compliance documents
    (OSHA, ASME, ISO, API standards) using the anomaly context as the query vector.

    Falls back to keyword matching if embeddings are unavailable.
    """
    # Build a text query from the anomaly data
    anomaly_text = (
        f"Asset: {asset_id}. "
        + " ".join(f"{k}: {v}" for k, v in anomaly_data.items() if isinstance(v, (str, int, float)))
    )

    # Try vector search first (requires OpenAI embeddings to be set up)
    embedding_str: Optional[str] = None
    if settings.OPENAI_API_KEY:
        try:
            import openai
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL,
                input=anomaly_text[:8000],
            )
            vec = resp.data[0].embedding
            embedding_str = "[" + ",".join(str(v) for v in vec) + "]"
        except Exception as e:
            logger.warning("rca_flow_embedding_failed", error=str(e))

    if embedding_str:
        rows = db.execute(
            text("""
                SELECT f.title, f.original_name, fc.content,
                       1 - (ce.embedding <=> CAST(:emb AS vector)) AS score
                FROM chunk_embeddings ce
                JOIN file_chunks fc ON fc.chunk_id = ce.chunk_id
                JOIN files f ON f.file_id = fc.file_id
                WHERE f.workspace_id = CAST(:wid AS uuid)
                  AND f.processing_status = 'done'
                  AND (
                      f.file_family = 'text_office'
                      OR f.title ILIKE '%OSHA%'
                      OR f.title ILIKE '%ASME%'
                      OR f.title ILIKE '%ISO%'
                      OR f.title ILIKE '%API%'
                      OR f.tags @> CAST(ARRAY['compliance'] AS text[])
                  )
                  AND 1 - (ce.embedding <=> CAST(:emb AS vector)) > 0.6
                ORDER BY score DESC
                LIMIT 10
            """),
            {"wid": workspace_id, "emb": embedding_str},
        ).fetchall()
    else:
        # Fallback: keyword search for compliance documents
        rows = db.execute(
            text("""
                SELECT f.title, f.original_name, fc.content, 0.7 AS score
                FROM files f
                JOIN file_chunks fc ON fc.file_id = f.file_id
                WHERE f.workspace_id = CAST(:wid AS uuid)
                  AND f.processing_status = 'done'
                  AND (
                      f.title ILIKE '%OSHA%' OR f.title ILIKE '%ASME%'
                      OR f.title ILIKE '%regulation%' OR f.title ILIKE '%compliance%'
                      OR fc.content ILIKE :asset_kw
                  )
                ORDER BY f.upload_ts DESC
                LIMIT 10
            """),
            {"wid": workspace_id, "asset_kw": f"%{asset_id}%"},
        ).fetchall()

    if not rows:
        return "No compliance documents found. Ensure regulatory standards (OSHA, ASME, ISO) are uploaded to the workspace."

    lines = ["FLOW GRAPH — Compliance Namespace Context:"]
    for row in rows:
        lines.append(
            f"\n  [{row.title or row.original_name}] (relevance: {row.score:.2f}):\n"
            f"  {row.content[:300]}..."
        )
    return "\n".join(lines)


# ─── Groq LLM Integration ─────────────────────────────────────────────────────

SOPRAG_SYSTEM_PROMPT = """You are an autonomous industrial RCA agent operating under strict regulatory constraints.
Use Counterfactual Reasoning to analyze the provided telemetry against the multi-view graph context.

You MUST respond with ONLY a valid JSON object matching this exact schema:
{
  "severity_level": "<CRITICAL|HIGH|MEDIUM|LOW>",
  "root_cause_summary": "<concise root cause analysis, 2-4 sentences>",
  "regulatory_violations": [
    {"standard": "<e.g. OSHA 1910.147>", "clause": "<specific clause>", "description": "<violation details>"}
  ],
  "predictive_recommendation": "<actionable maintenance recommendation, 2-3 sentences>"
}

Do not include any text outside the JSON object. Do not use markdown code blocks."""


def _call_groq_llm(
    entity_context: str,
    causal_context: str,
    flow_context: str,
    anomaly_data: Dict[str, Any],
    asset_id: str,
) -> Dict[str, Any]:
    """
    Calls the Groq LLM with the SOPRAG persona prompt and multi-view graph context.
    Returns parsed JSON matching the rca_insights schema.
    """
    if not settings.GROQ_API_KEY:
        logger.warning("rca_groq_key_missing", msg="GROQ_API_KEY not set. Returning placeholder insight.")
        return {
            "severity_level": "MEDIUM",
            "root_cause_summary": (
                f"Automated RCA for asset '{asset_id}' is unavailable — GROQ_API_KEY is not configured. "
                "Set the key in your .env file to enable full SOPRAG analysis."
            ),
            "regulatory_violations": [],
            "predictive_recommendation": "Configure GROQ_API_KEY and re-trigger analysis.",
        }

    import groq  # type: ignore

    client = groq.Groq(api_key=settings.GROQ_API_KEY)

    user_message = f"""
ANOMALY TELEMETRY:
Asset ID: {asset_id}
Anomaly Data: {json.dumps(anomaly_data, indent=2)}

--- VIEW 1: ENTITY GRAPH ---
{entity_context}

--- VIEW 2: CAUSAL GRAPH (Historical Failures + Shadow Connections) ---
{causal_context}

--- VIEW 3: FLOW GRAPH (Regulatory Compliance Namespace) ---
{flow_context}

Perform a counterfactual root cause analysis. What went wrong, what regulatory standards apply,
and what should maintenance teams do to prevent recurrence?
"""

    response = client.chat.completions.create(
        model=settings.GROQ_RCA_MODEL,
        messages=[
            {"role": "system", "content": SOPRAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_message[:32000]},  # safe context window
        ],
        temperature=0.2,   # low temperature for deterministic structured output
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw)

    # Validate required fields — provide defaults if LLM omits any
    return {
        "severity_level": parsed.get("severity_level", "MEDIUM"),
        "root_cause_summary": parsed.get("root_cause_summary", "Unable to determine root cause."),
        "regulatory_violations": parsed.get("regulatory_violations", []),
        "predictive_recommendation": parsed.get("predictive_recommendation", "No recommendation available."),
    }


# ─── Celery Task ──────────────────────────────────────────────────────────────

@celery_app.task(
    name="rca_agent.analyze_anomaly",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def analyze_anomaly_task(
    self,
    workspace_id: str,
    asset_id: str,
    anomaly_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    SOPRAG Predictive RCA Agent — Celery Task.

    Execution pipeline:
      1. Open a synchronous DB session.
      2. Run 3-view SOPRAG graph retrieval (entity / causal / flow).
      3. Call Groq LLM with counterfactual-reasoning persona prompt.
      4. Validate and parse the JSON response.
      5. Persist a new RcaInsight record to the database.

    Args:
        workspace_id:  UUID string of the target workspace.
        asset_id:      Industrial asset tag / identifier (e.g. "P-204", "TK001").
        anomaly_data:  Free-form telemetry dict (sensor readings, alert codes, etc.)

    Returns:
        dict with insight_id and summary fields on success.
    """
    logger.info("rca_task_start", workspace_id=workspace_id, asset_id=asset_id)

    try:
        db = _get_sync_session()

        # ── Step 1: Multi-view SOPRAG Retrieval ───────────────────────────────
        entity_context = _entity_graph_query(db, workspace_id, asset_id)
        causal_context = _causal_graph_query(db, workspace_id, asset_id)
        flow_context = _flow_graph_query(db, workspace_id, anomaly_data, asset_id)

        logger.info(
            "rca_retrieval_complete",
            workspace_id=workspace_id,
            asset_id=asset_id,
            entity_len=len(entity_context),
            causal_len=len(causal_context),
            flow_len=len(flow_context),
        )

        # ── Step 2: Groq LLM — Counterfactual RCA ────────────────────────────
        llm_result = _call_groq_llm(
            entity_context=entity_context,
            causal_context=causal_context,
            flow_context=flow_context,
            anomaly_data=anomaly_data,
            asset_id=asset_id,
        )

        # ── Step 3: Persist RcaInsight ────────────────────────────────────────
        from app.models import RcaInsight  # local import to avoid circular deps

        insight = RcaInsight(
            insight_id=uuid.uuid4(),
            workspace_id=uuid.UUID(workspace_id),
            asset_id=asset_id,
            severity_level=llm_result["severity_level"],
            root_cause_summary=llm_result["root_cause_summary"],
            regulatory_violations=llm_result["regulatory_violations"],
            predictive_recommendation=llm_result["predictive_recommendation"],
        )
        db.add(insight)
        db.commit()

        logger.info(
            "rca_task_complete",
            insight_id=str(insight.insight_id),
            severity=insight.severity_level,
        )

        return {
            "insight_id": str(insight.insight_id),
            "severity_level": insight.severity_level,
            "root_cause_summary": insight.root_cause_summary,
        }

    except Exception as exc:
        logger.error("rca_task_error", error=str(exc), workspace_id=workspace_id, asset_id=asset_id)
        raise self.retry(exc=exc)
    finally:
        try:
            db.close()
        except Exception:
            pass
