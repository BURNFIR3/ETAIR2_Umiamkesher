"""LLM service — uses Groq (free tier) for answer generation.

Model: llama-3.3-70b-versatile (Groq free tier)
Falls back to OpenAI if GROQ_API_KEY is not set and OPENAI_API_KEY is set.
"""
from typing import Tuple

from app.config import settings


SYSTEM_PROMPT = """You are an expert industrial document assistant for an asset-intensive industry platform.

Your role is to answer questions based ONLY on the provided document context.

Rules:
1. Answer only from the provided context. Do not use prior knowledge.
2. Always cite the source document by its File ID when using information from it.
3. If the context does not contain enough information to answer, say so clearly.
4. Be concise, precise, and technically accurate.
5. Use numbered lists or structured format when explaining procedures.
6. Never fabricate facts, specifications, or procedures.
7. If multiple documents give conflicting information, note the conflict and cite both.

Format your answer as:
[Your answer here]

Sources used: [List file IDs you referenced]
"""


async def generate_answer(
    query: str,
    context: str,
    use_strong_model: bool = False,
) -> Tuple[str, float, str]:
    """
    Generate a grounded answer from document context.
    Returns: (answer_text, confidence, model_name)

    Priority:
    1. Groq (GROQ_API_KEY) — free tier, llama-3.3-70b-versatile
    2. OpenAI (OPENAI_API_KEY) — fallback
    3. Neither configured → graceful error message
    """
    if settings.GROQ_API_KEY:
        return await _groq_answer(query, context, use_strong_model)
    elif settings.OPENAI_API_KEY:
        return await _openai_answer(query, context, use_strong_model)
    else:
        return (
            "AI query is not configured. Please set GROQ_API_KEY (free at console.groq.com) "
            "or OPENAI_API_KEY in the environment.",
            0.0,
            "none",
        )


async def _groq_answer(query: str, context: str, use_strong: bool) -> Tuple[str, float, str]:
    """Call Groq API with llama-3.3-70b-versatile."""
    model = settings.GROQ_CHAT_MODEL_STRONG if use_strong else settings.GROQ_CHAT_MODEL
    try:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"DOCUMENT CONTEXT:\n\n{context}\n\n---\n\nQUESTION: {query}",
            },
        ]

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=1500,
        )

        answer = response.choices[0].message.content.strip()
        confidence = _estimate_confidence(context, answer)
        return answer, confidence, f"groq/{model}"

    except Exception as e:
        import structlog
        structlog.get_logger().error("groq_error", error=str(e))
        return (
            "An error occurred while generating the answer. Please try again.",
            0.0,
            f"groq/{model}",
        )


async def _openai_answer(query: str, context: str, use_strong: bool) -> Tuple[str, float, str]:
    """Fallback: OpenAI GPT answer generation."""
    model = "gpt-4o" if use_strong else "gpt-4o-mini"
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"DOCUMENT CONTEXT:\n\n{context}\n\n---\n\nQUESTION: {query}",
            },
        ]

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=1500,
        )

        answer = response.choices[0].message.content.strip()
        confidence = _estimate_confidence(context, answer)
        return answer, confidence, f"openai/{model}"

    except Exception as e:
        import structlog
        structlog.get_logger().error("openai_error", error=str(e))
        return (
            "An error occurred while generating the answer. Please try again.",
            0.0,
            f"openai/{model}",
        )


def _estimate_confidence(context: str, answer: str) -> float:
    """Simple heuristic confidence based on context and answer length."""
    context_tokens = len(context) // 4
    answer_tokens = len(answer) // 4
    return round(min(0.95, 0.5 + (context_tokens / 3000) * 0.4 + (answer_tokens / 500) * 0.05), 2)


# ─── Pass 1: File selector ─────────────────────────────────────────────────────

FILE_SELECTOR_SYSTEM = """You are a document relevance classifier. You will receive:
1. A user query.
2. A JSON list of available documents with their metadata (title, keywords, tags, file_family).

Your task: Return ONLY a JSON array of the file_id values for documents that are relevant to the query.
Select at most 3 documents. If none are relevant, return an empty array [].
Do NOT include any explanation, markdown, or other text — only the raw JSON array.

Example output: ["uuid-1", "uuid-2"]"""


async def select_relevant_files(query: str, summaries: list) -> list:
    """
    Pass 1 LLM call — selects relevant file IDs from compact file metadata summaries.
    Returns a list of file_id strings (up to 3).
    Falls back to all summary file IDs if LLM fails or returns empty.
    """
    import json as _json
    import re

    if not summaries:
        return []

    # Build compact summary for LLM (strip description to reduce tokens)
    compact = [
        {
            "file_id": s["file_id"],
            "title": s["title"],
            "keywords": s["keywords"][:10],  # First 10 only
            "tags": s["tags"],
            "file_family": s["file_family"],
        }
        for s in summaries
    ]
    summaries_json = _json.dumps(compact, ensure_ascii=False)
    user_msg = f"QUERY: {query}\n\nDOCUMENTS:\n{summaries_json}"

    all_ids = [s["file_id"] for s in summaries]

    try:
        if settings.GROQ_API_KEY:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            response = await client.chat.completions.create(
                model=settings.GROQ_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": FILE_SELECTOR_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            raw = response.choices[0].message.content.strip()
        elif settings.OPENAI_API_KEY:
            import openai
            client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": FILE_SELECTOR_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            raw = response.choices[0].message.content.strip()
        else:
            # No LLM configured — return all (fallback)
            return all_ids[:3]

        # Robustly extract JSON array from response
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            selected = _json.loads(match.group(0))
            # Validate returned IDs are actually in our accessible list
            valid = [fid for fid in selected if fid in all_ids]
            if valid:
                return valid[:3]

    except Exception as e:
        import structlog
        structlog.get_logger().warning("file_selector_llm_error", error=str(e))

    # Fallback: return all (bounded by top 3)
    return all_ids[:3]
