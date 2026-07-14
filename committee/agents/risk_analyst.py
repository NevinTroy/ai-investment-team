"""Risk Analyst Agent.

Answers "what could go wrong?" for a prospective investment. It works in two steps:

    1. Classify the company's industry / regulatory domain using an LLM so the
       risk searches are grounded (e.g. "Stripe" -> "payments / fintech",
       regulated by financial-services authorities).
    2. Research the COMPANY's risk surface via the Tavily MCP across six
       dimensions: regulatory exposure, key-person risk, market timing risk,
       lawsuits & litigation, layoffs & restructuring, and negative press.

It then asks an LLM to synthesize the evidence into a structured signal:

    {"risk_score": 7.1, "confidence": 0.78, "red_flags": [...], "reasoning": "..."}

``risk_score`` follows the committee convention that higher is better for the
investment: 10 = minimal risk, 0 = severe red flags.
"""

import json
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress

from committee.tools.tavily_mcp import tavily_search

logger = logging.getLogger("committee.risk_analyst")

# Max characters of evidence to keep per search dimension (keeps the prompt
# focused and within context limits).
_MAX_EVIDENCE_CHARS_PER_DIMENSION = 2500


class RiskContext(BaseModel):
    """The company's industry/regulatory context, used to seed the risk research."""

    industry: str = Field(description="The specific industry the company operates in, e.g. 'online payments / fintech'.")
    regulatory_domain: str = Field(description="The regulatory regime(s) most relevant to this company, e.g. 'financial services regulation (PSD2, money transmission licensing)'.")


class RiskAnalysis(BaseModel):
    """Structured output requested from the LLM."""

    risk_score: float = Field(description="Risk profile on a 0-10 scale where HIGHER IS SAFER (10 = minimal risk, 0 = severe red flags).")
    confidence: float = Field(description="Confidence in the assessment from 0.0 to 1.0.")
    reasoning: str = Field(description="Concise justification grounded in the gathered evidence.")
    red_flags: list[str] = Field(default_factory=list, description="Specific red flags found in the evidence (lawsuits, layoffs, negative press, regulatory actions, key-person dependencies). Empty if none.")
    data: dict = Field(default_factory=dict, description="Risk facts from the evidence: regulatory actions, lawsuit names/status, layoff counts and dates, executive departures, etc.")


class RiskAnalystOutput(BaseModel):
    """Verified, final output of the Risk Analyst agent.

    This model enforces the output contract after the agent runs: scores are
    clamped to their valid ranges, reasoning is non-empty, and all context
    fields are present. Constructing it validates the agent's result before it
    is stored in state or returned to the chat layer.
    """

    company: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    regulatory_domain: str = Field(min_length=1)
    risk_score: float = Field(ge=0.0, le=10.0, description="Risk profile, 0-10 (higher is safer).")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence, 0.0-1.0.")
    reasoning: str = Field(min_length=1)
    red_flags: list[str] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)

    @field_validator("risk_score", mode="before")
    @classmethod
    def _clamp_risk_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, float(v))), 2)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return round(max(0.0, min(1.0, float(v))), 2)

    @field_validator("company", "industry", "regulatory_domain", "reasoning", mode="before")
    @classmethod
    def _strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


def _classify_risk_context(company: str, question: str, state: AgentState, agent_id: str) -> RiskContext:
    """Use an LLM to determine the industry and regulatory domain for the company."""
    prompt = f"""You are a risk classification expert on an investment committee.

The committee is evaluating: "{question}"
Company: {company}

Identify the INDUSTRY this company operates in and the REGULATORY DOMAIN most
relevant to it, so its risk surface can be researched
(e.g. company "Stripe" -> industry "online payments / fintech",
regulatory domain "financial services regulation, money transmission licensing").

Respond in JSON format with EXACTLY these keys:
{{
  "industry": "<specific industry the company operates in>",
  "regulatory_domain": "<the regulatory regime(s) most relevant to this company>"
}}
"""
    return call_llm(
        prompt=prompt,
        pydantic_model=RiskContext,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: RiskContext(
            industry="Unknown",
            regulatory_domain="Unknown",
        ),
    )


def _search_dimensions(company: str, industry: str) -> dict[str, str]:
    """Return the six risk queries to run for the company."""
    return {
        "regulatory_exposure": f"{company} {industry} regulatory risk compliance investigation fine enforcement",
        "key_person_risk": f"{company} founder CEO executive departure resignation key person dependence",
        "market_timing_risk": f"{industry} market downturn headwinds demand slowdown timing risk 2026",
        "lawsuits": f"{company} lawsuit litigation legal action settlement court",
        "layoffs": f"{company} layoffs restructuring job cuts workforce reduction",
        "negative_press": f"{company} controversy scandal criticism negative press",
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


def _build_evidence(company: str, industry: str, agent_id: str, status_label: str) -> tuple[dict[str, str], list[dict]]:
    """Run all risk searches for the company.

    Returns a ``(evidence, search_log)`` tuple where ``evidence`` maps each
    dimension to summarized text and ``search_log`` records the query and a
    preview of the result for each dimension (for display/logging).
    """
    dimensions = _search_dimensions(company, industry)
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


def _build_prompt(company: str, industry: str, regulatory_domain: str, question: str, evidence: dict[str, str]) -> str:
    evidence_block = "\n\n".join(
        f"## {dimension.replace('_', ' ').upper()}\n{text}" for dimension, text in evidence.items()
    )
    return f"""You are a risk analyst on an investment committee evaluating: "{question}"

Company under consideration: {company}
Industry: {industry}
Regulatory domain: {regulatory_domain}

The web research below covers the company's risk surface. Using ONLY this
evidence, assess the investment risk across all six dimensions: regulatory
exposure, key-person risk, market timing risk, lawsuits & litigation,
layoffs & restructuring, and negative press.

Be skeptical and evidence-based. Distinguish material risks (active regulatory
enforcement, pending lawsuits with real exposure, founder departures, repeated
mass layoffs) from noise (routine complaints, isolated critical articles).
If evidence is thin or conflicting, lower your confidence.

Scoring convention (IMPORTANT): risk_score is 0-10 where HIGHER IS SAFER.
10 = minimal risk with no material red flags; 5 = notable but manageable risks;
0 = severe red flags that could impair the investment.

=== WEB RESEARCH EVIDENCE (about the company: {company}) ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "risk_score": <float 0-10, higher is safer>,
  "confidence": <float 0.0-1.0, your confidence in this assessment>,
  "reasoning": "<2-4 sentences citing the strongest evidence>",
  "red_flags": ["<specific red flag with source context>", "..."],
  "data": {{"<risk fact>": "<value from the evidence, e.g. lawsuit name/status, layoff count, regulatory action>"}}
}}
"""


def risk_analyst_agent(state: AgentState, agent_id: str = "risk_analyst_agent"):
    """Classify the company's risk context, research its risk surface, and produce a signal."""
    data = state.get("data", {})
    company = data.get("company")
    question = data.get("question", f"Should we invest in {company}?")

    # Step 1: classify the company's industry/regulatory domain via the LLM.
    progress.update_status(agent_id, company, "Classifying risk context")
    context = _classify_risk_context(company, question, state, agent_id)
    industry = context.industry
    regulatory_domain = context.regulatory_domain
    status_label = f"{company} -> {industry}"

    # Step 2: research the COMPANY's risk surface.
    progress.update_status(agent_id, status_label, "Gathering risk evidence")
    evidence, search_log = _build_evidence(company, industry, agent_id, status_label)

    progress.update_status(agent_id, status_label, "Synthesizing risk assessment")
    prompt = _build_prompt(company, industry, regulatory_domain, question, evidence)

    analysis = call_llm(
        prompt=prompt,
        pydantic_model=RiskAnalysis,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: RiskAnalysis(
            risk_score=0.0,
            confidence=0.0,
            reasoning="Unable to analyze risk due to an error gathering or synthesizing evidence.",
            red_flags=[],
            data={},
        ),
    )

    # Verify the agent's output against the Pydantic contract (range checks,
    # clamping, non-empty fields) before it leaves the agent.
    progress.update_status(agent_id, status_label, "Verifying output")
    try:
        verified = RiskAnalystOutput(
            company=company,
            industry=industry,
            regulatory_domain=regulatory_domain,
            risk_score=analysis.risk_score,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            red_flags=analysis.red_flags,
            data=analysis.data,
        )
    except ValidationError as exc:
        logger.warning("Risk analyst output failed verification: %s", exc)
        verified = RiskAnalystOutput(
            company=company or "Unknown",
            industry=industry or "Unknown",
            regulatory_domain=regulatory_domain or "Unknown",
            risk_score=0.0,
            confidence=0.0,
            reasoning="Output failed validation; defaulting to a zero-confidence, maximum-caution assessment.",
        )

    result = verified.model_dump()

    if "analysis" not in state["data"]:
        state["data"]["analysis"] = {}
    state["data"]["analysis"]["risk_analyst"] = result

    # Record the search log so the chat layer can display the queries + results.
    state["data"].setdefault("search_log", {})["risk_analyst"] = search_log

    progress.update_status(agent_id, status_label, "Done", analysis=json.dumps(result, indent=2))

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(result, "Risk Analyst Agent")

    # Surface the detected industry/regulatory domain in the search log header too.
    search_log.insert(
        0,
        {
            "dimension": "classification",
            "query": f"(LLM) risk context for {company}",
            "result_preview": f"industry: {industry} | regulatory domain: {regulatory_domain}",
        },
    )
    state["data"]["search_log"]["risk_analyst"] = search_log

    message = HumanMessage(content=json.dumps(result), name=agent_id)

    return {
        "messages": [message],
        "data": state["data"],
    }
