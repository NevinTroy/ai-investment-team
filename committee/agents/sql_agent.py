"""Read-only data-retrieval agent for the investment-committee database.

A ReAct-style agent (LangGraph ``create_react_agent``) whose whole job is to
*retrieve* data — e.g. "find me the fintech companies" -> read the ``chats``
table filtered by sector — and answer in plain English.

It reaches the database through the **existing Supabase client** — the same
``SUPABASE_URL`` / ``SUPABASE_SERVICE_ROLE_KEY`` used by
``committee/persistence.py`` — via Supabase's PostgREST API. Read-only is
guaranteed *structurally*: the agent's tools only ever call ``.select()``. No
insert/update/delete/DDL method is exposed anywhere, so the agent physically
cannot modify the database.

Like ``committee/persistence.py``, this module is *fail-soft*: missing Supabase
config never raises on import — the agent just reports that it is unavailable.

Reference: https://docs.langchain.com/oss/python/langgraph/sql-agent
"""

import json
import logging

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool

from committee.persistence import get_supabase_client
from src.llm.models import get_model
from src.utils.llm import get_default_max_tokens, get_default_model_config

logger = logging.getLogger("committee.sql_agent")

# Cap how much a single query can pull back, so a stray "select all" can't dump a
# whole table into the model's context.
MAX_ROWS = 50

# The tables the agent is allowed to read. Mirrors supabase/schema.sql.
KNOWN_TABLES = ("chats", "messages", "agent_outputs", "decks", "network_neighbors", "followups")

# PostgREST filter operators the agent may use — all read-only comparisons.
_FILTER_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in", "is"}


def _apply_filter(query, column: str, op: str, value):
    """Apply one {column, op, value} filter to a PostgREST query builder."""
    if not column:
        raise ValueError("Each filter needs a 'column'.")
    op = (op or "eq").lower()
    if op not in _FILTER_OPS:
        raise ValueError(f"Unsupported operator '{op}'. Allowed: {', '.join(sorted(_FILTER_OPS))}.")
    if op == "in":
        values = value if isinstance(value, list) else [value]
        return query.in_(column, values)
    if op == "is":
        return query.is_(column, value)
    return getattr(query, op)(column, value)


@tool
def list_tables() -> str:
    """List the tables that can be queried. Call this first to see what exists."""
    return ", ".join(KNOWN_TABLES)


@tool
def get_schema(table: str) -> str:
    """Return the column names and up to 3 sample rows for a table, so you use
    real column names when querying."""
    client = get_supabase_client()
    if client is None:
        return "Error: Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)."
    if table not in KNOWN_TABLES:
        return f"Error: unknown table '{table}'. Available: {', '.join(KNOWN_TABLES)}."
    try:
        res = client.table(table).select("*").limit(3).execute()
        rows = res.data or []
        columns = sorted(rows[0].keys()) if rows else "(table is empty; columns unknown)"
        return json.dumps({"table": table, "columns": columns, "sample_rows": rows}, default=str, indent=2)
    except Exception as exc:
        logger.exception("get_schema failed")
        return f"Error reading schema for {table}: {exc}"


@tool
def query_table(
    table: str,
    columns: str = "*",
    filters: list[dict] = None,
    order_by: str = "",
    descending: bool = False,
    limit: int = MAX_ROWS,
) -> str:
    """Read rows from a table (READ-ONLY) and return them as JSON.

    Args:
      table: one of the known tables (see list_tables).
      columns: comma-separated column list, or "*" for all.
      filters: list of {"column": .., "op": .., "value": ..}. op is one of
        eq, neq, gt, gte, lt, lte, like, ilike, in, is. For text such as sector,
        prefer ilike with wildcards, e.g.
        {"column": "sector", "op": "ilike", "value": "%fintech%"}.
      order_by: column to sort by (optional).
      descending: sort descending when true.
      limit: max rows to return (capped at 50).
    """
    client = get_supabase_client()
    if client is None:
        return "Error: Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)."
    if table not in KNOWN_TABLES:
        return f"Error: unknown table '{table}'. Available: {', '.join(KNOWN_TABLES)}."
    try:
        query = client.table(table).select(columns or "*")
        for spec in filters or []:
            query = _apply_filter(query, spec.get("column"), spec.get("op", "eq"), spec.get("value"))
        if order_by:
            query = query.order(order_by, desc=bool(descending))
        query = query.limit(min(int(limit or MAX_ROWS), MAX_ROWS))
        res = query.execute()
        rows = res.data or []
        return json.dumps({"row_count": len(rows), "rows": rows}, default=str)
    except ValueError as exc:
        return f"Rejected: {exc}"
    except Exception as exc:
        logger.exception("query_table failed")
        return f"Error querying {table}: {exc}"


_SYSTEM_PROMPT = (
    "You are a careful data analyst for an AI investment committee. Your ONLY job "
    "is to RETRIEVE data and answer the user's question. You can read data but "
    "never modify it — the tools only support reading.\n\n"
    "Workflow:\n"
    "- Call list_tables to see what exists, then get_schema on the relevant table "
    "to learn its real column names.\n"
    "- Use query_table to read the rows you need.\n\n"
    "The primary table is `chats` (one row per analysis run). Key columns: id, "
    "title, company, sector, question, status, created_at. The `sector` column is "
    "a short comma-separated list like 'fintech, finance', so match it with the "
    "ilike operator and wildcards (e.g. filter {\"column\": \"sector\", \"op\": "
    "\"ilike\", \"value\": \"%fintech%\"}) rather than exact equality.\n\n"
    "After you get the rows, answer the user's question in plain English and, when "
    "useful, list the matching companies. If a query errors, read the message, fix "
    "your arguments, and retry."
)


def build_sql_agent():
    """Build the read-only retrieval agent, or return None if unavailable."""
    if get_supabase_client() is None:
        return None
    try:
        from langgraph.prebuilt import create_react_agent

        model_name, model_provider = get_default_model_config()
        model = get_model(model_name, model_provider, max_tokens=get_default_max_tokens())
        return create_react_agent(
            model,
            tools=[list_tables, get_schema, query_table],
            state_modifier=_SYSTEM_PROMPT,
        )
    except Exception:
        logger.exception("Failed to build SQL agent")
        return None


def _message_text(message: BaseMessage) -> str:
    """Flatten a message's content to plain text (handles Anthropic block lists)."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)


def run_sql_agent(question: str, recursion_limit: int = 25) -> dict:
    """Answer a natural-language data question by reading the database read-only.

    Returns ``{"question", "answer", "queries", "error"}``. ``error`` is set (and
    ``answer`` empty) when the agent could not run. ``queries`` lists the
    ``query_table`` calls the agent made.
    """
    agent = build_sql_agent()
    if agent is None:
        return {
            "question": question,
            "answer": "",
            "queries": [],
            "error": "SQL agent unavailable — set SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (see .env.example).",
        }

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=question)]},
            config={"recursion_limit": recursion_limit},
        )
    except Exception as exc:
        logger.exception("run_sql_agent failed")
        return {"question": question, "answer": "", "queries": [], "error": str(exc)}

    messages = result.get("messages", [])

    # Record the reads the agent actually performed (query_table tool calls).
    queries: list[dict] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == "query_table":
                queries.append(call.get("args") or {})

    answer = _message_text(messages[-1]) if messages else ""
    return {"question": question, "answer": answer, "queries": queries, "error": None}


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    # Running this module directly doesn't go through api.py/main.py, so load
    # .env here the same way they do (repo root, then project root override).
    _repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(_repo_root / ".env")
    load_dotenv(_repo_root.parent / ".env", override=True)

    logging.basicConfig(level=logging.INFO)
    q = " ".join(sys.argv[1:]) or "Find me the fintech companies."
    out = run_sql_agent(q)
    print(json.dumps(out, indent=2, default=str))
