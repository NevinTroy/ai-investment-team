"""Competitive Intelligence Agent.

Answers "who competes with this product and how do they compare?" for a
prospective investment. It works in these steps:

    1. Tavily web research for product context and competitor landscape.
    2. An LLM identifies the product and top 3 direct competitors.
    3. Tavily deep-dives on funding, revenue, and ARR/MRR for the target + competitors.
    4. An LLM synthesizes a comparison table and competitive assessment.
"""

import json
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress

from committee.tools.tavily_competitors import (
    TOP_COMPETITORS,
    gather_competitor_landscape,
    gather_company_metrics,
    gather_product_evidence,
)

logger = logging.getLogger("committee.competitive_intelligence")


class ProductCompetitorIdentification(BaseModel):
    """The product and its top competitors, used to seed the research."""

    product_name: str = Field(description="The company's main product/service name.")
    category: str = Field(description="What the product is / its category.")
    is_saas: bool = Field(description="True if the product is a SaaS or subscription software product.")
    competitors: list[str] = Field(
        default_factory=list,
        description=f"Exactly {TOP_COMPETITORS} direct competitor company names, ranked by relevance.",
    )


class CompanyMetrics(BaseModel):
    name: str = Field(description="Company name.")
    fund_raised: str = Field(default="", description="Total funding raised.")
    revenue: str = Field(default="", description="Annual revenue if known.")
    mrr_arr: str = Field(default="", description="MRR or ARR for SaaS; use N/A when not applicable.")
    dynamic_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Product-specific comparison fields keyed by row label.",
    )


class ComparisonTableSpec(BaseModel):
    dynamic_row_labels: list[str] = Field(
        default_factory=list,
        description="3-6 product-specific comparison row labels (e.g. Pricing, Target Customer).",
    )
    companies: list[CompanyMetrics] = Field(
        default_factory=list,
        description="Target company first, then each competitor.",
    )


class CompetitiveSynthesis(BaseModel):
    """Structured output from the final LLM synthesis step."""

    competitive_score: float = Field(description="Competitive position strength on a 0-10 scale.")
    confidence: float = Field(description="Confidence in the assessment from 0.0 to 1.0.")
    reasoning: str = Field(description="Concise justification grounded in the gathered evidence.")
    comparison_table: ComparisonTableSpec = Field(default_factory=ComparisonTableSpec)
    data: dict = Field(default_factory=dict, description="Extra competitive intelligence facts.")


class CompetitiveIntelligenceOutput(BaseModel):
    """Verified, final output of the Competitive Intelligence agent."""

    company: str = Field(min_length=1)
    product: str = Field(min_length=1)
    competitive_score: float = Field(ge=0.0, le=10.0, description="Competitive position strength, 0-10.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence, 0.0-1.0.")
    reasoning: str = Field(min_length=1)
    top_competitors: list[str] = Field(default_factory=list)
    markdown_table: str = Field(default="", description="Markdown comparison table.")
    data: dict = Field(default_factory=dict)

    @field_validator("competitive_score", mode="before")
    @classmethod
    def _clamp_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, float(v))), 2)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return round(max(0.0, min(1.0, float(v))), 2)

    @field_validator("company", "product", "reasoning", mode="before")
    @classmethod
    def _strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


def _identify_product_and_competitors(
    company: str,
    question: str,
    evidence: dict[str, str],
    state: AgentState,
    agent_id: str,
) -> ProductCompetitorIdentification:
    evidence_block = "\n\n".join(
        f"## {dimension.replace('_', ' ').upper()}\n{text}" for dimension, text in evidence.items()
    )
    prompt = f"""You are a competitive intelligence expert on an investment committee.

The committee is evaluating: "{question}"
Company: {company}

Using ONLY the web research below, identify:
1. The company's main PRODUCT name and CATEGORY
2. Whether the product is a SaaS / subscription software product (is_saas)
3. Exactly {TOP_COMPETITORS} direct COMPETITORS (company names), ranked by relevance

Use exact competitor names from the evidence. Do NOT invent competitors.
Exclude {company} itself. Return fewer than {TOP_COMPETITORS} only if evidence names fewer.

=== WEB RESEARCH ===
{evidence_block or "(no evidence)"}
=== END RESEARCH ===

Respond in JSON format with EXACTLY these keys:
{{
  "product_name": "<main product/service>",
  "category": "<product category>",
  "is_saas": <true|false>,
  "competitors": ["<most relevant competitor>", "...", "<third>"]
}}
"""
    return call_llm(
        prompt=prompt,
        pydantic_model=ProductCompetitorIdentification,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: ProductCompetitorIdentification(
            product_name=company,
            category="Unknown",
            is_saas=False,
            competitors=[],
        ),
    )


def _build_synthesis_prompt(
    company: str,
    product: str,
    category: str,
    question: str,
    is_saas: bool,
    competitors: list[str],
    evidence: dict[str, str],
) -> str:
    evidence_block = "\n\n".join(
        f"## {dimension.replace('_', ' ').upper()}\n{text}" for dimension, text in evidence.items()
    )
    arr_instruction = (
        "Include mrr_arr for every company (use N/A when unknown)."
        if is_saas
        else "Set mrr_arr to N/A for every company (not a SaaS product)."
    )
    return f"""You are a competitive intelligence analyst on an investment committee evaluating: "{question}"

Company under consideration: {company}
Product: {product}
Category: {category}
Is SaaS: {is_saas}
Top competitors: {', '.join(competitors)}

Using ONLY the research below, build a comparison table and competitive assessment.

Required metrics for EVERY company (target first, then competitors):
- fund_raised
- revenue
- mrr_arr — {arr_instruction}

Also choose 3-6 product-specific dynamic_row_labels relevant to this category
(e.g. "Pricing", "Target Customer", "Key Features", "Integrations").
Populate dynamic_fields on each company using those labels as keys.

Use "—" or "Unknown" when data is not in the evidence. Do NOT invent figures.

=== WEB RESEARCH EVIDENCE ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "competitive_score": <float 0-10, how strong {company}'s competitive position is>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-4 sentences citing the strongest evidence>",
  "comparison_table": {{
    "dynamic_row_labels": ["<row label>", "..."],
    "companies": [
      {{
        "name": "<company name>",
        "fund_raised": "<value or —>",
        "revenue": "<value or —>",
        "mrr_arr": "<value, —, or N/A>",
        "dynamic_fields": {{"<row label>": "<value>"}}
      }}
    ]
  }},
  "data": {{"<metric>": "<value>"}}
}}
"""


def _escape_md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _build_comparison_table(table: ComparisonTableSpec, *, is_saas: bool) -> str:
    """Build a factor-rows x company-columns markdown comparison table."""
    if not table.companies:
        return "(No comparison data available.)"

    column_names = [c.name or "Unknown" for c in table.companies]
    header = "| | " + " | ".join(_escape_md_cell(name) for name in column_names) + " |"
    separator = "| --- | " + " | ".join(["---"] * len(column_names)) + " |"
    lines = [header, separator]

    required_rows = ["Fund Raised", "Revenue"]
    if is_saas:
        required_rows.append("MRR/ARR")

    def cell_for(company: CompanyMetrics, row: str) -> str:
        if row == "Fund Raised":
            return company.fund_raised or "—"
        if row == "Revenue":
            return company.revenue or "—"
        if row == "MRR/ARR":
            return company.mrr_arr or "—"
        return company.dynamic_fields.get(row, "—")

    all_rows = required_rows + [label for label in table.dynamic_row_labels if label not in required_rows]
    for row in all_rows:
        cells = [row] + [cell_for(company, row) for company in table.companies]
        lines.append("| " + " | ".join(_escape_md_cell(str(c)) for c in cells) + " |")

    return "\n".join(lines)


def competitive_intelligence_agent(state: AgentState, agent_id: str = "competitive_intelligence_agent"):
    """Identify top 3 competitors via Tavily and compare them."""
    data = state.get("data", {})
    company = data.get("company")
    question = data.get("question", f"Should we invest in {company}?")
    search_log: list[dict] = []
    evidence: dict[str, str] = {}

    progress.update_status(agent_id, company, "Tavily: product research")
    product_evidence, product_log = gather_product_evidence(company)
    evidence.update(product_evidence)
    search_log.extend(product_log)

    progress.update_status(agent_id, company, "Tavily: competitor landscape")
    landscape_evidence, landscape_log = gather_competitor_landscape(company, company, "software")
    evidence.update(landscape_evidence)
    search_log.extend(landscape_log)

    progress.update_status(agent_id, company, "Identifying product & top competitors")
    identification = _identify_product_and_competitors(company, question, evidence, state, agent_id)
    product = identification.product_name or company or "Unknown"
    category = identification.category or "Unknown"
    is_saas = identification.is_saas
    competitors = list(dict.fromkeys(identification.competitors))[:TOP_COMPETITORS]
    status_label = f"{company} -> {product}"

    if len(competitors) < TOP_COMPETITORS:
        progress.update_status(agent_id, status_label, "Refreshing landscape with product context")
        refined_landscape, refined_log = gather_competitor_landscape(company, product, category)
        evidence.update(refined_landscape)
        search_log.extend(refined_log)
        identification = _identify_product_and_competitors(company, question, evidence, state, agent_id)
        product = identification.product_name or product
        category = identification.category or category
        is_saas = identification.is_saas
        competitors = list(dict.fromkeys(identification.competitors))[:TOP_COMPETITORS]

    progress.update_status(agent_id, status_label, "Tavily: company metrics deep-dive")
    all_companies = [company] + competitors
    for name in all_companies:
        progress.update_status(agent_id, status_label, f"Metrics: {name}")
        metrics_evidence, metrics_log = gather_company_metrics(name, category, include_arr=is_saas)
        evidence.update(metrics_evidence)
        search_log.extend(metrics_log)

    progress.update_status(agent_id, status_label, "Synthesizing comparison table")
    synthesis_prompt = _build_synthesis_prompt(
        company, product, category, question, is_saas, competitors, evidence
    )
    synthesis = call_llm(
        prompt=synthesis_prompt,
        pydantic_model=CompetitiveSynthesis,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: CompetitiveSynthesis(
            competitive_score=0.0,
            confidence=0.0,
            reasoning="Unable to analyze competitors due to an error gathering or synthesizing evidence.",
            comparison_table=ComparisonTableSpec(),
            data={},
        ),
    )

    markdown_table = _build_comparison_table(synthesis.comparison_table, is_saas=is_saas)

    progress.update_status(agent_id, status_label, "Verifying output")
    try:
        verified = CompetitiveIntelligenceOutput(
            company=company,
            product=product,
            competitive_score=synthesis.competitive_score,
            confidence=synthesis.confidence,
            reasoning=synthesis.reasoning,
            top_competitors=competitors,
            markdown_table=markdown_table,
            data=synthesis.data,
        )
    except ValidationError as exc:
        logger.warning("Competitive intelligence output failed verification: %s", exc)
        verified = CompetitiveIntelligenceOutput(
            company=company or "Unknown",
            product=product or "Unknown",
            competitive_score=0.0,
            confidence=0.0,
            reasoning="Output failed validation; defaulting to a neutral, zero-confidence assessment.",
            top_competitors=competitors,
            markdown_table=markdown_table,
        )

    result = verified.model_dump()

    if "analysis" not in state["data"]:
        state["data"]["analysis"] = {}
    state["data"]["analysis"]["competitive_intelligence"] = result

    search_log.insert(
        0,
        {
            "dimension": "identification",
            "query": f"(Tavily + LLM) product & top {TOP_COMPETITORS} competitors for {company}",
            "result_preview": (
                f"product: {product} | category: {category} | is_saas: {is_saas} | "
                f"competitors: {', '.join(competitors) or 'none identified'}"
            ),
        },
    )
    state["data"].setdefault("search_log", {})["competitive_intelligence"] = search_log

    progress.update_status(agent_id, status_label, "Done", analysis=json.dumps(result, indent=2))

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(result, "Competitive Intelligence Agent")

    message = HumanMessage(content=json.dumps(result), name=agent_id)

    return {
        "messages": [message],
        "data": state["data"],
    }
