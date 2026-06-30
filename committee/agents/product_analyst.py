"""Product Analyst Agent.

Answers "how strong is the product?" for a prospective investment. It works in
these steps:

    1. Identify the PRODUCT of the company. Identification is grounded in a
       Tavily web lookup first (so obscure companies the LLM has never heard of
       are still resolved to a real product), then an LLM extracts the product
       name, website, and category from that evidence.
    2. Research the product via the Tavily MCP across the evaluation dimensions:
       product quality, differentiation, defensibility, technical moat,
       features, and roadmap. Queries also pull from the requested input
       sources: demo videos, docs, the website, and customer reviews.
    3. An LLM synthesizes the evidence into a structured signal:

    {"product_score": 8.4, "confidence": 0.71, "reasoning": "...", "data": {...}}
"""

import json
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress

from committee.tools.tavily_mcp import tavily_search

logger = logging.getLogger("committee.product_analyst")

# Max characters of evidence to keep per search dimension (keeps the prompt
# focused and within context limits).
_MAX_EVIDENCE_CHARS_PER_DIMENSION = 2500


class ProductIdentification(BaseModel):
    """The product a company offers, used to seed the research."""

    product_name: str = Field(description="The company's main product/service name, e.g. 'Stripe Payments'. Used as the search subject.")
    website: str = Field(default="", description="The product's official website/URL if known.")
    category: str = Field(description="What the product is / its category, e.g. 'payments API for online businesses'.")


class ProductAnalysis(BaseModel):
    """Structured output requested from the LLM."""

    product_score: float = Field(description="Strength of the product on a 0-10 scale (10 = exceptional).")
    confidence: float = Field(description="Confidence in the assessment from 0.0 to 1.0.")
    reasoning: str = Field(description="Concise justification grounded in the gathered evidence.")
    data: dict = Field(default_factory=dict, description="Structured product facts: key features, differentiators, roadmap items, defensibility/moat notes, review sentiment. Any kind of quantitive data")


class ProductAnalyzerOutput(BaseModel):
    """Verified, final output of the Product Analyst agent.

    This model enforces the output contract after the agent runs: scores are
    clamped to their valid ranges, reasoning is non-empty, and all context
    fields are present. Constructing it validates the agent's result before it
    is stored in state or returned to the chat layer.
    """

    company: str = Field(min_length=1)
    product: str = Field(min_length=1)
    product_score: float = Field(ge=0.0, le=10.0, description="Product strength, 0-10.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence, 0.0-1.0.")
    reasoning: str = Field(min_length=1)
    data: dict = Field(default_factory=dict, description="Structured product facts: key features, differentiators, roadmap items, defensibility/moat notes, review sentiment. Any kind of quantitive data")

    @field_validator("product_score", mode="before")
    @classmethod
    def _clamp_product_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, float(v))), 2)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return round(max(0.0, min(1.0, float(v))), 2)

    @field_validator("company", "product", "reasoning", mode="before")
    @classmethod
    def _strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


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


def _lookup_product_evidence(company: str, agent_id: str, status_label: str) -> str:
    """Run a Tavily lookup for the company's product/offering.

    This grounds identification in live web data so the LLM does not have to
    rely on prior knowledge for companies it has never seen.
    """
    query = f"{company} product what it does website overview"
    progress.update_status(agent_id, status_label, "Looking up product")
    results = tavily_search([query], max_results=5)
    result = results[0] if results else {}
    if not result or "error" in result:
        return ""
    return _summarize_result(result.get("result", ""))


def _identify_product(company: str, question: str, product_evidence: str, state: AgentState, agent_id: str) -> ProductIdentification:
    """Use an LLM to determine the company's product, website, and category.

    Grounded in ``product_evidence`` (web lookup) so obscure companies resolve to
    a real product rather than a placeholder.
    """
    evidence_block = product_evidence.strip() or "(no web evidence found)"
    prompt = f"""You are a product research expert on an investment committee.

The committee is evaluating: "{question}"
Company: {company}

Using the WEB EVIDENCE below, identify the company's main PRODUCT (name), its
official WEBSITE if present, and its CATEGORY (what the product is). Be specific
so the product can be researched on its own (e.g. company "Stripe" -> product
"Stripe Payments", category "payments API for online businesses"). Do NOT invent
facts. If the evidence does not name a product, use the company name as the
product.

=== WEB EVIDENCE (about {company}) ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "product_name": "<the company's main product/service name>",
  "website": "<official product website/URL or empty>",
  "category": "<what the product is / its category>"
}}
"""
    return call_llm(
        prompt=prompt,
        pydantic_model=ProductIdentification,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: ProductIdentification(
            product_name=company,
            website="",
            category="Unknown",
        ),
    )


def _search_dimensions(product: str, company: str, category: str) -> dict[str, str]:
    """Return the product research queries to run (evaluation criteria + input sources)."""
    return {
        "product_quality": f"{product} {company} product quality reliability user experience",
        "differentiation": f"{product} {company} differentiation vs competitors unique selling points",
        "defensibility": f"{product} {company} defensibility switching costs network effects lock-in",
        "technical_moat": f"{product} {company} technology technical moat patents architecture",
        "features": f"{product} {company} features capabilities",
        "roadmap": f"{product} {company} roadmap upcoming features vision future",
        "customer_reviews": f"{company} {product} customer reviews G2 Capterra Trustpilot ratings",
    }


def _build_evidence(product: str, company: str, category: str, agent_id: str, status_label: str) -> tuple[dict[str, str], list[dict]]:
    """Run all product searches.

    Returns a ``(evidence, search_log)`` tuple where ``evidence`` maps each
    dimension to summarized text and ``search_log`` records the query and a
    preview of the result for each dimension (for display/logging).
    """
    dimensions = _search_dimensions(product, company, category)
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


def _build_prompt(company: str, product: str, category: str, question: str, evidence: dict[str, str]) -> str:
    evidence_block = "\n\n".join(
        f"## {dimension.replace('_', ' ').upper()}\n{text}" for dimension, text in evidence.items()
    )
    return f"""You are a product analyst on an investment committee evaluating: "{question}"

Company under consideration: {company}
Product being assessed: {product}
Category: {category}

The web research below is about the PRODUCT. Using ONLY this evidence, assess the
strength of the product. Consider product quality, differentiation,
defensibility, technical moat, features, and roadmap. The evidence draws from
demo videos, documentation, the website, and customer reviews.

Be skeptical and evidence-based. If evidence is thin or conflicting, lower your
confidence. A great product is high quality, clearly differentiated, defensible
(switching costs / network effects), backed by a real technical moat, feature-
rich, and on a credible forward roadmap.

=== WEB RESEARCH EVIDENCE (about the product: {product}) ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "product_score": <float 0-10, product strength>,
  "confidence": <float 0.0-1.0, your confidence in this assessment>,
  "reasoning": "<2-4 sentences citing the strongest evidence>",
  "data": {{
    "key_features": ["<feature>", "..."],
    "differentiators": ["<what sets it apart>", "..."],
    "roadmap": ["<upcoming item>", "..."],
    "defensibility": "<moat / switching costs / network effects notes>",
    "review_sentiment": "<summary of customer review sentiment>"
  }}
}}
"""


def product_analyst_agent(state: AgentState, agent_id: str = "product_analyst_agent"):
    """Identify the company's product, research it, and produce a signal."""
    data = state.get("data", {})
    company = data.get("company")
    question = data.get("question", f"Should we invest in {company}?")

    # Step 1: identify the product, grounded in a web lookup.
    progress.update_status(agent_id, company, "Identifying product")
    product_evidence = _lookup_product_evidence(company, agent_id, company)
    identification = _identify_product(company, question, product_evidence, state, agent_id)
    product = identification.product_name or company or "Unknown"
    category = identification.category or "Unknown"
    status_label = f"{company} -> {product}"

    # Step 2: research the PRODUCT.
    progress.update_status(agent_id, status_label, "Gathering product evidence")
    evidence, search_log = _build_evidence(product, company, category, agent_id, status_label)

    progress.update_status(agent_id, status_label, "Synthesizing product assessment")
    prompt = _build_prompt(company, product, category, question, evidence)

    analysis = call_llm(
        prompt=prompt,
        pydantic_model=ProductAnalysis,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: ProductAnalysis(
            product_score=0.0,
            confidence=0.0,
            reasoning="Unable to analyze the product due to an error gathering or synthesizing evidence.",
            data={},
        ),
    )

    # Verify the agent's output against the Pydantic contract (range checks,
    # clamping, non-empty fields) before it leaves the agent.
    progress.update_status(agent_id, status_label, "Verifying output")
    try:
        verified = ProductAnalyzerOutput(
            company=company,
            product=product,
            product_score=analysis.product_score,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            data=analysis.data,
        )
    except ValidationError as exc:
        logger.warning("Product analyst output failed verification: %s", exc)
        verified = ProductAnalyzerOutput(
            company=company or "Unknown",
            product=product or "Unknown",
            product_score=0.0,
            confidence=0.0,
            reasoning="Output failed validation; defaulting to a neutral, zero-confidence assessment.",
        )

    result = verified.model_dump()

    if "analysis" not in state["data"]:
        state["data"]["analysis"] = {}
    state["data"]["analysis"]["product_analyst"] = result

    # Record the search log so the chat layer can display the queries + results.
    state["data"].setdefault("search_log", {})["product_analyst"] = search_log

    progress.update_status(agent_id, status_label, "Done", analysis=json.dumps(result, indent=2))

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(result, "Product Analyst Agent")

    # Surface the detected product/category in the search log header too.
    search_log.insert(
        0,
        {
            "dimension": "identification",
            "query": f"(web + LLM) product for {company}",
            "result_preview": f"product: {product} | category: {category}",
        },
    )
    state["data"]["search_log"]["product_analyst"] = search_log

    message = HumanMessage(content=json.dumps(result), name=agent_id)

    return {
        "messages": [message],
        "data": state["data"],
    }
