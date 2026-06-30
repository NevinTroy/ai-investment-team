"""Fetch founder headshots via Tavily image search and store them locally."""

import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from committee.tools.tavily_mcp import tavily_search

logger = logging.getLogger("committee.tavily_founder_images")

_SKIP_URL_RE = re.compile(r"(favicon|logo|icon|sprite|badge|emoji|pixel|1x1|tracking|analytics)", re.I)
_PORTRAIT_HINT_RE = re.compile(
    r"(headshot|portrait|founder|ceo|co-founder|executive|profile|speaker|team)",
    re.I,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"


def founder_images_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    return here / "founder_images"


def founder_image_dir(company: str) -> Path:
    return founder_images_root() / _slug(company)


def _parse_tavily_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _image_entry_to_url(entry: Any) -> tuple[str, str]:
    if isinstance(entry, str):
        return entry, ""
    if isinstance(entry, dict):
        return str(entry.get("url") or entry.get("src") or ""), str(entry.get("description") or "")
    return "", ""


def extract_image_candidates(raw: Any) -> list[dict[str, str]]:
    """Collect image URL candidates from a Tavily search payload."""
    payload = _parse_tavily_payload(raw)
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str, description: str = "") -> None:
        url = url.strip()
        if not url or url in seen or _SKIP_URL_RE.search(url):
            return
        seen.add(url)
        candidates.append({"url": url, "description": description})

    for entry in payload.get("images") or []:
        url, description = _image_entry_to_url(entry)
        add(url, description)

    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        for entry in result.get("images") or []:
            url, description = _image_entry_to_url(entry)
            title = str(result.get("title") or "")
            add(url, description or title)

    return candidates


def _score_candidate(name: str, company: str, candidate: dict[str, str]) -> int:
    url = candidate.get("url", "")
    description = candidate.get("description", "")
    haystack = f"{url} {description}".lower()
    score = 0
    name_parts = [part.lower() for part in name.split() if len(part) > 2]
    if any(part in haystack for part in name_parts):
        score += 4
    if company.lower() in haystack:
        score += 2
    if _PORTRAIT_HINT_RE.search(haystack):
        score += 3
    if any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
        score += 1
    if "linkedin" in url.lower():
        score += 1
    return score


def pick_founder_image_url(name: str, company: str, candidates: list[dict[str, str]]) -> str | None:
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda c: _score_candidate(name, company, c), reverse=True)
    return ranked[0]["url"]


def search_founder_image_url(name: str, company: str) -> tuple[str | None, dict[str, str]]:
    """Search Tavily for a founder photo and return the best image URL."""
    query = f"{name} {company} founder CEO co-founder headshot portrait photo"
    results = tavily_search(
        [query],
        max_results=4,
        search_depth="advanced",
        include_images=True,
        include_image_descriptions=True,
    )
    result = results[0] if results else {}
    log_entry = {
        "dimension": f"founder_image:{name}",
        "query": query,
        "result_preview": "",
    }
    if not result or "error" in result:
        log_entry["result_preview"] = f"(image search failed: {result.get('error', 'no result') if result else 'no result'})"
        return None, log_entry

    candidates = extract_image_candidates(result.get("result", ""))
    image_url = pick_founder_image_url(name, company, candidates)
    log_entry["result_preview"] = image_url or f"(no suitable image from {len(candidates)} candidates)"
    return image_url, log_entry


def _extension_from_response(url: str, content_type: str | None) -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ext
    return ".jpg"


def download_founder_image(image_url: str, dest_base: Path, *, timeout: float = 30.0) -> str | None:
    """Download an image. Returns the saved local path on success."""
    dest_base.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "SummitCommittee/1.0"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(image_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type and not content_type.startswith("image/"):
                logger.warning("Skipping non-image content-type %s for %s", content_type, image_url)
                return None
            data = response.content
            if len(data) < 5_000:
                logger.warning("Skipping tiny image (%s bytes) for %s", len(data), image_url)
                return None
            final_path = dest_base.with_suffix(_extension_from_response(image_url, content_type))
            final_path.write_bytes(data)
            return str(final_path)
    except Exception as exc:
        logger.warning("Failed to download founder image %s: %s", image_url, exc)
        return None


def fetch_and_store_founder_image(name: str, company: str) -> tuple[str, str, dict[str, str]]:
    """Search Tavily, download the best founder image, and return ``(local_path, source_url, log_entry)``."""
    image_url, log_entry = search_founder_image_url(name, company)
    if not image_url:
        return "", "", log_entry

    local_path = download_founder_image(image_url, founder_image_dir(company) / _slug(name))
    if local_path:
        log_entry["result_preview"] = f"saved {local_path} from {image_url}"
        return local_path, image_url, log_entry

    log_entry["result_preview"] = f"(download failed for {image_url})"
    return "", image_url, log_entry
