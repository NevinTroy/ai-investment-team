"""Tavily-based competitor research helpers for the competitive intelligence agent."""

import json
from typing import Any

from committee.tools.tavily_mcp import tavily_search

TOP_COMPETITORS = 3
MAX_EVIDENCE_CHARS = 2500


def summarize_tavily_result(raw: Any) -> str:
    """Extract readable text (answer + result snippets) from a Tavily MCP result."""
    text = raw if isinstance(raw, str) else json.dumps(raw)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:MAX_EVIDENCE_CHARS]

    parts: list[str] = []
    if isinstance(payload, dict):
        if payload.get("answer"):
            parts.append(f"Answer: {payload['answer']}")
        for item in payload.get("results", []) or []:
            title = item.get("title", "")
            content = item.get("content", "")
            url = item.get("url", "")
            parts.append(f"- {title} ({url})\n  {content}")
    summary = "\n".join(parts) if parts else text
    return summary[:MAX_EVIDENCE_CHARS]


def tavily_lookup(query: str, *, max_results: int = 5) -> tuple[str, dict[str, str]]:
    """Run a Tavily search and return ``(summary, log_entry)``."""
    results = tavily_search([query], max_results=max_results)
    result = results[0] if results else {}
    if not result or "error" in result:
        summary = f"(search failed: {result.get('error', 'no result') if result else 'no result'})"
    else:
        summary = summarize_tavily_result(result.get("result", ""))
    log_entry = {"query": query, "result_preview": summary[:800]}
    return summary, log_entry


def _collect_searches(
    queries: dict[str, str],
    *,
    max_results: int = 5,
) -> tuple[dict[str, str], list[dict]]:
    evidence: dict[str, str] = {}
    search_log: list[dict] = []
    for dimension, query in queries.items():
        summary, log_entry = tavily_lookup(query, max_results=max_results)
        evidence[dimension] = summary
        search_log.append({"dimension": dimension, **log_entry})
    return evidence, search_log


def gather_product_evidence(company: str) -> tuple[dict[str, str], list[dict]]:
    """Product overview and target-company financial signals."""
    queries = {
        "product_overview": f"{company} product what it does website overview",
        "target_funding": f"{company} funding raised total venture capital",
        "target_revenue": f"{company} revenue annual",
        "target_arr": f"{company} ARR MRR recurring revenue subscription",
    }
    return _collect_searches(queries)


def gather_competitor_landscape(company: str, product: str, category: str) -> tuple[dict[str, str], list[dict]]:
    """Competitor discovery and market landscape searches."""
    queries = {
        "competitor_alternatives": f"{company} competitors alternatives similar products",
        "competitor_landscape": f"{product} {category} competitors alternatives market landscape",
        "feature_comparison": f"{product} {company} vs competitors features comparison",
        "pricing_comparison": f"{product} {category} competitors pricing plans cost",
    }
    return _collect_searches(queries, max_results=4)


def gather_company_metrics(
    company_name: str,
    category: str,
    *,
    include_arr: bool,
) -> tuple[dict[str, str], list[dict]]:
    """Focused financial and product metrics for one company."""
    queries = {
        f"{company_name}:funding": f"{company_name} funding raised total venture capital",
        f"{company_name}:revenue": f"{company_name} revenue annual",
        f"{company_name}:product": f"{company_name} {category} product features pricing",
    }
    if include_arr:
        queries[f"{company_name}:arr"] = f"{company_name} ARR MRR recurring revenue subscription"
    return _collect_searches(queries, max_results=4)
