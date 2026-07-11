"""Supabase persistence for chats, agent outputs, decks, and network snapshots.

Every function here is best-effort: a Supabase outage or missing credentials
must never break the live analysis/SSE flow, so failures are logged and
swallowed rather than raised. Every function besides ``create_chat`` treats
``chat_id is None`` as a no-op.

Set SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in your environment (see
supabase/schema.sql for the tables to create, and create a public Storage
bucket named "decks").
"""

import json
import logging
import mimetypes
import os
from typing import Any

import httpx

logger = logging.getLogger("committee.persistence")

DECKS_BUCKET = "decks"

_client = None
_client_checked = False


def get_supabase_client():
    """Lazy singleton Supabase client, or None if not configured."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.warning("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not set — chat persistence disabled.")
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
    except Exception:
        logger.exception("Failed to create Supabase client — chat persistence disabled.")
        _client = None
    return _client


def create_chat(question: str, company: str) -> str | None:
    """Insert a new chat row with status='running'. Returns the chat_id, or None on failure."""
    client = get_supabase_client()
    if client is None:
        return None
    try:
        row = {
            "title": company or (question[:80] if question else "Untitled"),
            "company": company or "",
            "question": question,
            "status": "running",
        }
        res = client.table("chats").insert(row).execute()
        return res.data[0]["id"]
    except Exception:
        logger.exception("create_chat failed")
        return None


def save_user_message(chat_id: str | None, content: str) -> None:
    _insert_message(chat_id, "user", content)


def save_assistant_message(chat_id: str | None, content: str) -> None:
    _insert_message(chat_id, "assistant", content)


def _insert_message(chat_id: str | None, role: str, content: str) -> None:
    if not chat_id:
        return
    client = get_supabase_client()
    if client is None:
        return
    try:
        client.table("messages").insert({
            "chat_id": chat_id,
            "role": role,
            "content": content or "",
        }).execute()
    except Exception:
        logger.exception("save message failed for chat %s", chat_id)


def save_agent_output(chat_id: str | None, agent_name: str, ticker: str, raw_analysis: str) -> None:
    """Persist one agent's final verbose JSON output as its own row.

    Called as soon as that agent finishes (not just once at the end of the
    whole run), independent of the consolidated copy in chats.analysis.
    """
    if not chat_id or not raw_analysis:
        return
    client = get_supabase_client()
    if client is None:
        return
    try:
        output = json.loads(raw_analysis)
    except (TypeError, ValueError):
        output = {"raw": raw_analysis}
    try:
        client.table("agent_outputs").upsert(
            {
                "chat_id": chat_id,
                "agent_name": agent_name,
                "ticker": ticker or "",
                "output": output,
            },
            on_conflict="chat_id,agent_name",
        ).execute()
    except Exception:
        logger.exception("save_agent_output failed for chat %s agent %s", chat_id, agent_name)


def mark_chat_rejected(chat_id: str | None, reason: str) -> None:
    _update_chat_status(chat_id, "rejected", error_message=reason)


def mark_chat_error(chat_id: str | None, message: str) -> None:
    _update_chat_status(chat_id, "error", error_message=message)


def _update_chat_status(chat_id: str | None, status: str, **fields: Any) -> None:
    if not chat_id:
        return
    client = get_supabase_client()
    if client is None:
        return
    try:
        from datetime import datetime, timezone
        client.table("chats").update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }).eq("id", chat_id).execute()
    except Exception:
        logger.exception("update chat status failed for chat %s", chat_id)


def save_chat_result(chat_id: str | None, analysis: dict, neighbors: list, new_pos: tuple) -> None:
    """Persist the final agent analysis + network snapshot, mark status='done'."""
    _update_chat_status(
        chat_id,
        "done",
        analysis=analysis,
        network_snapshot={"neighbors": neighbors, "new_pos": list(new_pos) if new_pos else None},
    )


def save_network_neighbors(chat_id: str | None, company: str, neighbors: list) -> None:
    """Persist the top-N portfolio neighbours (with similarity score) as individual
    rows, one per neighbour, alongside the compact copy in chats.network_snapshot.
    """
    if not chat_id or not neighbors:
        return
    client = get_supabase_client()
    if client is None:
        return
    rows = [
        {
            "chat_id": chat_id,
            "company": company or "",
            "rank": i + 1,
            "neighbor_id": n.get("id"),
            "neighbor_name": n.get("name", ""),
            "neighbor_sector": n.get("sector", ""),
            "similarity": n.get("similarity", 0.0),
            "x": n.get("x"),
            "y": n.get("y"),
        }
        for i, n in enumerate(neighbors)
    ]
    try:
        client.table("network_neighbors").upsert(rows, on_conflict="chat_id,neighbor_id").execute()
    except Exception:
        logger.exception("save_network_neighbors failed for chat %s", chat_id)


def download_and_store_deck(
    chat_id: str | None,
    presentation_url: str,
    edit_path: str,
    company: str,
) -> dict | None:
    """Download the generated PDF and upload it into the "decks" Storage bucket.

    Returns the inserted deck row, or None on any failure (missing chat_id,
    missing presentation_url, network error, missing Supabase config, etc).
    """
    if not chat_id or not presentation_url:
        return None
    client = get_supabase_client()
    if client is None:
        return None

    try:
        with httpx.Client(timeout=60.0) as http_client:
            response = http_client.get(presentation_url)
        response.raise_for_status()
        pdf_bytes = response.content
    except Exception:
        logger.exception("Failed to download deck PDF for chat %s", chat_id)
        return None

    file_name = f"Investment-Memo-{(company or 'Company').replace(' ', '-')}.pdf"
    storage_path = f"{chat_id}/{file_name}"
    content_type = mimetypes.guess_type(file_name)[0] or "application/pdf"

    try:
        client.storage.from_(DECKS_BUCKET).upload(
            storage_path,
            pdf_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        public_url = client.storage.from_(DECKS_BUCKET).get_public_url(storage_path)
    except Exception:
        logger.exception("Failed to upload deck PDF to storage for chat %s", chat_id)
        return None

    try:
        row = {
            "chat_id": chat_id,
            "storage_path": storage_path,
            "public_url": public_url,
            "edit_path": edit_path or "",
            "file_name": file_name,
            "content_type": content_type,
            "file_size_bytes": len(pdf_bytes),
        }
        res = client.table("decks").insert(row).execute()
        return res.data[0] if res.data else row
    except Exception:
        logger.exception("Failed to save deck row for chat %s", chat_id)
        return None


def list_chats(limit: int = 50) -> list[dict]:
    client = get_supabase_client()
    if client is None:
        return []
    try:
        res = (
            client.table("chats")
            .select("id,title,company,question,status,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception:
        logger.exception("list_chats failed")
        return []


def get_chat(chat_id: str) -> dict | None:
    client = get_supabase_client()
    if client is None:
        return None
    try:
        chat_res = client.table("chats").select("*").eq("id", chat_id).limit(1).execute()
        if not chat_res.data:
            return None
        chat = chat_res.data[0]

        deck_res = (
            client.table("decks")
            .select("*")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        chat["deck"] = deck_res.data[0] if deck_res.data else None

        messages_res = (
            client.table("messages")
            .select("*")
            .eq("chat_id", chat_id)
            .order("created_at")
            .execute()
        )
        chat["messages"] = messages_res.data or []

        agent_outputs_res = (
            client.table("agent_outputs")
            .select("*")
            .eq("chat_id", chat_id)
            .order("created_at")
            .execute()
        )
        chat["agent_outputs"] = agent_outputs_res.data or []

        neighbors_res = (
            client.table("network_neighbors")
            .select("*")
            .eq("chat_id", chat_id)
            .order("rank")
            .execute()
        )
        chat["network_neighbors"] = neighbors_res.data or []

        return chat
    except Exception:
        logger.exception("get_chat failed for chat %s", chat_id)
        return None
