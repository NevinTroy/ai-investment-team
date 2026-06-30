"""Presenton presentation generation API client.

Docs: https://api.presenton.ai/api/v3/presentation/generate

Set ``PRESENTON_API_KEY`` in your environment (Bearer token).
"""

import logging
import mimetypes
import os
from typing import Any

import httpx

PRESENTON_GENERATE_URL = "https://api.presenton.ai/api/v3/presentation/generate"
PRESENTON_IMAGE_UPLOAD_URL = "https://api.presenton.ai/api/v3/images/upload"

logger = logging.getLogger("committee.presenton")


def _api_key() -> str:
    key = os.environ.get("PRESENTON_API_KEY")
    if not key:
        raise RuntimeError(
            "PRESENTON_API_KEY is not set. Add it to your .env to generate investment memo decks."
        )
    return key


def _presentation_defaults() -> dict[str, Any]:
    smart_design = os.environ.get(
        "PRESENTON_SMART_DESIGN",
        "990d88ea-9ca6-4a74-bc11-52cf55a993c9",
    )
    defaults: dict[str, Any] = {
        "tone": os.environ.get("PRESENTON_TONE", "default"),
        "verbosity": os.environ.get("PRESENTON_VERBOSITY", "standard"),
        "image_type": os.environ.get("PRESENTON_IMAGE_TYPE", "ai-generated"),
        "export_as": os.environ.get("PRESENTON_EXPORT_AS", "pdf"),
        "markdown_emphasis": False,
        "include_table_of_contents": False,
        "include_title_slide": False,
        "allow_access_to_user_info": False,
    }
    if smart_design:
        defaults["smart_design"] = smart_design
    else:
        defaults["theme"] = os.environ.get("PRESENTON_THEME", "mint-blue")
    return defaults


def upload_image(file_path: str) -> dict[str, Any]:
    """Upload a local image to Presenton and return the ImageAsset payload."""
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Founder image not found: {path}")

    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {_api_key()}",
    }
    with open(path, "rb") as handle:
        files = {"file": (os.path.basename(path), handle, mime_type)}
        with httpx.Client(timeout=60.0) as client:
            response = client.post(PRESENTON_IMAGE_UPLOAD_URL, headers=headers, files=files)
    response.raise_for_status()
    data = response.json()
    logger.info("Presenton image uploaded: %s", data.get("url") or data.get("path") or path)
    return data if isinstance(data, dict) else {"raw": data}


def generate_presentation(
    slides: list[dict[str, str]],
    *,
    content_generation: str | None = "preserve",
) -> dict[str, Any]:
    """POST /api/v3/presentation/generate and return the JSON response."""
    payload = {
        **_presentation_defaults(),
        "slides": slides,
        "content_generation": content_generation or "preserve",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {_api_key()}",
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(PRESENTON_GENERATE_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        logger.info("Presenton presentation generated: %s", extract_presentation_url(data) or "ok")
        return data if isinstance(data, dict) else {"raw": data}
    except RuntimeError:
        raise
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        logger.warning("Presenton generate_presentation HTTP error: %s", detail)
        raise RuntimeError(f"Presenton API error: {detail}") from exc
    except Exception as exc:
        logger.warning("Presenton generate_presentation failed: %s", exc)
        raise


def extract_presentation_url(payload: dict[str, Any]) -> str:
    """Return Presenton's exported file URL (PDF/PPTX) — use the API ``path`` field as-is."""
    path = payload.get("path")
    if isinstance(path, str) and path.startswith("http"):
        return path
    for key in ("presentation_url", "download_url", "pdf_url", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_presentation_url(data)
    return ""


def extract_edit_path(payload: dict[str, Any]) -> str:
    """Return Presenton's editor URL (separate from the exported PDF)."""
    edit_path = payload.get("edit_path")
    return edit_path if isinstance(edit_path, str) else ""


def _extract_url(payload: dict[str, Any]) -> str | None:
    """Backward-compatible alias for ``extract_presentation_url``."""
    url = extract_presentation_url(payload)
    return url or None
