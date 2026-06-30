"""Market Analyzer Agent.

Answers "what is the market?" for a prospective investment. It works in two steps:

    1. Classify the company into the MARKET / SECTOR it operates in using an LLM
       (e.g. "Abode Healthcare" -> market "hospice & palliative care",
       sector "Healthcare & Life Sciences").
    2. Research that MARKET (not the company) via the Tavily MCP across six
       dimensions: TAM/SAM/SOM, market growth (CAGR), market timing,
       competitive landscape, regulatory trends, and emerging technologies.

It then asks an LLM to synthesize the evidence into a structured signal:

    {"market_score": 8.9, "confidence": 0.82, "reasoning": "..."}
"""

import json
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress

from committee.tools.tavily_mcp import tavily_search

logger = logging.getLogger("committee.market_analyzer")

# Max characters of evidence to keep per search dimension (keeps the prompt
# focused and within context limits).
_MAX_EVIDENCE_CHARS_PER_DIMENSION = 2500


class MarketClassification(BaseModel):
    """The market/sector a company operates in, used to seed the research."""

    market: str = Field(description="The specific market/industry the company operates in, e.g. 'hospice & palliative care services'. Used as the search subject.")
    sectors: list[str] = Field(description="The broad sectors, e.g. ['Healthcare & Life Sciences', 'Hospice & Palliative Care'].")

class MarketAnalysis(BaseModel):
    """Structured output requested from the LLM."""

    market_score: float = Field(description="Attractiveness of the market on a 0-10 scale (10 = exceptional).")
    confidence: float = Field(description="Confidence in the assessment from 0.0 to 1.0.")
    reasoning: str = Field(description="Concise justification grounded in the gathered evidence.")
    data: dict = Field(default_factory=dict, description="Data about the market, sector, and company. Any kind of quantitive data")


class MarketAnalyzerOutput(BaseModel):
    """Verified, final output of the Market Analyzer agent.

    This model enforces the output contract after the agent runs: scores are
    clamped to their valid ranges, reasoning is non-empty, and all context
    fields are present. Constructing it validates the agent's result before it
    is stored in state or returned to the chat layer.
    """

    company: str = Field(min_length=1)
    market: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    market_score: float = Field(ge=0.0, le=10.0, description="Market attractiveness, 0-10.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence, 0.0-1.0.")
    reasoning: str = Field(min_length=1)
    data: dict = Field(default_factory=dict, description="Data about the market, sector, and company. Any kind of quantitive data")

    @field_validator("market_score", mode="before")
    @classmethod
    def _clamp_market_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, float(v))), 2)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return round(max(0.0, min(1.0, float(v))), 2)

    @field_validator("company", "market", "sector", "reasoning", mode="before")
    @classmethod
    def _strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


def _classify_market(company: str, question: str, state: AgentState, agent_id: str) -> MarketClassification:
    """Use an LLM to determine the market and sector the company operates in."""
    prompt = f"""You are an industry classification expert on an investment committee.

The committee is evaluating: "{question}"
Company: {company}

Identify the MARKET (specific industry/segment) and broad SECTOR this company
operates in. Be specific  about the market so it can be researched on its own
(e.g. company "Abode Healthcare" -> market "hospice & palliative care services",
sector "Healthcare & Life Sciences").

Respond in JSON format with EXACTLY these keys:
{{
  "market": "<specific market/industry the company operates in>",
  "sectors": ["<broad sector>", "<optional additional sector>"]
}}
"""
    return call_llm(
        prompt=prompt,
        pydantic_model=MarketClassification,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: MarketClassification(
            market=company,
            sectors=["Unknown"],
        ),
    )


def _search_dimensions(market: str, sector: str) -> dict[str, str]:
    """Return the six market queries to run for a market/sector (not the company)."""
    return {
        "tam_sam_som": f"{market} market size TAM SAM SOM total addressable market",
        "market_growth": f"{market} market growth rate CAGR forecast",
        "timing": f"{market} market timing demand trends maturity 2026",
        "competitive_landscape": f"{market} competitive landscape key players market share",
        "emerging_technologies": f"{market} emerging technologies innovation disruption",
    }


def _summarize_result(raw) -> str:
    """Extract readable text (answer + result snippets) from a Tavily MCP result."""
    text = raw if isinstance(raw, str) else json.dumps(raw)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:_MAX_EVIDENCE_CHARS_PER_DIMENSION]

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
    return summary[:_MAX_EVIDENCE_CHARS_PER_DIMENSION]


def _build_evidence(market: str, sector: str, agent_id: str, status_label: str) -> tuple[dict[str, str], list[dict]]:
    """Run all market searches against the market/sector.

    Returns a ``(evidence, search_log)`` tuple where ``evidence`` maps each
    dimension to summarized text and ``search_log`` records the query and a
    preview of the result for each dimension (for display/logging).
    """
    dimensions = _search_dimensions(market, sector)
    evidence: dict[str, str] = {}
    search_log: list[dict] = []

    for dimension, query in dimensions.items():
        label = dimension.replace("_", " ")
        progress.update_status(agent_id, status_label, f"Searching: {label}")
        results = tavily_search([query], max_results=4)
        result = results[0] if results else {}
        if "error" in result:
            summary = f"(search failed: {result['error']})"
            evidence[dimension] = summary
        else:
            summary = _summarize_result(result.get("result", ""))
            evidence[dimension] = summary

        search_log.append(
            {
                "dimension": dimension,
                "query": query,
                "result_preview": summary[:800],
            }
        )

    return evidence, search_log


def _build_prompt(company: str, market: str, sector: str, question: str, evidence: dict[str, str]) -> str:
    evidence_block = "\n\n".join(
        f"## {dimension.replace('_', ' ').upper()}\n{text}" for dimension, text in evidence.items()
    )
    return f"""You are a market analyst on an investment committee evaluating: "{question}"

Company under consideration: {company}
Market being assessed: {market}
Sector: {sector}

The web research below is about the MARKET/SECTOR (not the specific company).
Using ONLY this evidence, assess the attractiveness of this market. Consider all
six dimensions: TAM/SAM/SOM, market growth (CAGR), market timing, competitive
landscape, regulatory trends, and emerging technologies.

Be skeptical and evidence-based. If evidence is thin or conflicting, lower your
confidence. A great market is large, growing fast (>20% CAGR is exceptional),
well-timed, with favorable regulation and tailwinds from emerging tech.

=== WEB RESEARCH EVIDENCE (about the market: {market}) ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "market_score": <float 0-10, market attractiveness>,
  "confidence": <float 0.0-1.0, your confidence in this assessment>,
  "reasoning": "<2-4 sentences citing the strongest evidence>",
  "data": {{"<metric name>": "<quantitative value from the evidence, e.g. TAM, CAGR, market share>"}}
}}
"""


def market_analyzer_agent(state: AgentState, agent_id: str = "market_analyzer_agent"):
    """Classify the company's market, research that market, and produce a signal."""
    data = state.get("data", {})
    company = data.get("company")
    question = data.get("question", f"Should we invest in {company}?")

    # Step 1: classify the company into its market/sector via the LLM.
    progress.update_status(agent_id, company, "Classifying market/sector")
    classification = _classify_market(company, question, state, agent_id)
    market = classification.market
    sector = ", ".join(classification.sectors) if classification.sectors else "Unknown"
    status_label = f"{company} -> {market}"

    # Step 2: research the MARKET (not the company).
    progress.update_status(agent_id, status_label, "Gathering market evidence")
    evidence, search_log = _build_evidence(market, sector, agent_id, status_label)

    progress.update_status(agent_id, status_label, "Synthesizing market assessment")
    prompt = _build_prompt(company, market, sector, question, evidence)

    analysis = call_llm(
        prompt=prompt,
        pydantic_model=MarketAnalysis,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: MarketAnalysis(
            market_score=0.0,
            confidence=0.0,
            reasoning="Unable to analyze the market due to an error gathering or synthesizing evidence.",
            data={},
        ),
    )

    # Verify the agent's output against the Pydantic contract (range checks,
    # clamping, non-empty fields) before it leaves the agent.
    progress.update_status(agent_id, status_label, "Verifying output")
    try:
        verified = MarketAnalyzerOutput(
            company=company,
            market=market,
            sector=sector,
            market_score=analysis.market_score,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            data=analysis.data,
        )
    except ValidationError as exc:
        logger.warning("Market analyzer output failed verification: %s", exc)
        verified = MarketAnalyzerOutput(
            company=company or "Unknown",
            market=market or "Unknown",
            sector=sector or "Unknown",
            market_score=0.0,
            confidence=0.0,
            reasoning="Output failed validation; defaulting to a neutral, zero-confidence assessment.",
        )

    result = verified.model_dump()

    if "analysis" not in state["data"]:
        state["data"]["analysis"] = {}
    state["data"]["analysis"]["market_analyzer"] = result

    # Record the search log so the chat layer can display the queries + results.
    state["data"].setdefault("search_log", {})["market_analyzer"] = search_log

    progress.update_status(agent_id, status_label, "Done", analysis=json.dumps(result, indent=2))

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(result, "Market Analyzer Agent")

    # Surface the detected market/sector in the search log header too.
    search_log.insert(
        0,
        {
            "dimension": "classification",
            "query": f"(LLM) market for {company}",
            "result_preview": f"market: {market} | sector: {sector}",
        },
    )
    state["data"]["search_log"]["market_analyzer"] = search_log

    message = HumanMessage(content=json.dumps(result), name=agent_id)

    return {
        "messages": [message],
        "data": state["data"],
    }
