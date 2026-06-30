"""Tavily MCP search tool.

Connects to Tavily's remote MCP server over streamable HTTP using
``langchain-mcp-adapters`` and exposes a simple synchronous ``tavily_search``
helper that committee agents can call to ground their analysis in live web data.
"""

import asyncio
import json
import logging
import os
import threading
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

TAVILY_MCP_BASE_URL = "https://mcp.tavily.com/mcp/"

logger = logging.getLogger("committee.tavily")


def _result_snippet(raw: Any, limit: int = 300) -> str:
    """Build a short, human-readable snippet describing a Tavily result."""
    text = raw if isinstance(raw, str) else json.dumps(raw)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:limit]

    if isinstance(payload, dict):
        results = payload.get("results") or []
        titles = [r.get("title", "") for r in results[:3] if isinstance(r, dict)]
        head = "; ".join(t for t in titles if t)
        return f"{len(results)} results | {head}"[:limit]
    return text[:limit]


def _mcp_url() -> str:
    """Build the Tavily MCP URL with the API key from the environment."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Add it to your .env so the Market "
            "Analyzer can reach the Tavily MCP server."
        )
    return f"{TAVILY_MCP_BASE_URL}?tavilyApiKey={api_key}"


def _normalize_result(result: Any) -> Any:
    """Coerce an MCP tool result into something JSON-serializable / printable."""
    if isinstance(result, (str, dict, list)):
        return result
    # langchain tools may return message-like objects; fall back to str.
    return str(result)


async def _search_async(
    queries: list[str],
    *,
    max_results: int,
    search_depth: str,
    include_images: bool = False,
    include_image_descriptions: bool = False,
) -> list[dict[str, Any]]:
    client = MultiServerMCPClient(
        {
            "tavily": {
                "transport": "streamable_http",
                "url": _mcp_url(),
            }
        }
    )

    tools = await client.get_tools()
    search_tool = next((t for t in tools if "search" in t.name.lower()), None)
    if search_tool is None:
        available = ", ".join(t.name for t in tools) or "<none>"
        raise RuntimeError(
            f"Tavily MCP did not expose a search tool. Available tools: {available}"
        )

    results: list[dict[str, Any]] = []
    for query in queries:
        logger.info("Tavily search query: %s", query)
        try:
            raw = await search_tool.ainvoke(
                {
                    "query": query,
                    "search_depth": search_depth,
                    "max_results": max_results,
                    "include_images": include_images,
                    "include_image_descriptions": include_image_descriptions,
                }
            )
            normalized = _normalize_result(raw)
            logger.info("Tavily search result for %r -> %s", query, _result_snippet(normalized))
            results.append({"query": query, "result": normalized})
        except Exception as exc:  # keep the agent resilient to a single bad query
            logger.warning("Tavily search failed for %r: %s", query, exc)
            results.append({"query": query, "error": str(exc)})
    return results


def tavily_search(
    queries: list[str],
    *,
    max_results: int = 5,
    search_depth: str = "advanced",
    include_images: bool = False,
    include_image_descriptions: bool = False,
) -> list[dict[str, Any]]:
    """Run one or more web searches through the Tavily MCP server.

    Returns a list of ``{"query": ..., "result": ...}`` dicts (or
    ``{"query": ..., "error": ...}`` when an individual query fails).

    Safe to call from synchronous code (e.g. a LangGraph node). If an event
    loop is already running, the search runs in a dedicated worker thread.
    """
    if isinstance(queries, str):
        queries = [queries]

    coro_factory = lambda: _search_async(
        queries,
        max_results=max_results,
        search_depth=search_depth,
        include_images=include_images,
        include_image_descriptions=include_image_descriptions,
    )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop: safe to use asyncio.run directly.
        return asyncio.run(coro_factory())

    # A loop is already running in this thread; offload to a separate thread
    # with its own event loop so we don't conflict with it.
    box: dict[str, Any] = {}

    def _runner() -> None:
        box["value"] = asyncio.run(coro_factory())

    worker = threading.Thread(target=_runner)
    worker.start()
    worker.join()
    return box["value"]
