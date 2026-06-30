"""Founder Analyzer Agent.

Answers "how strong are the founders?" for a prospective investment. It works
in these steps:

    1. Identify the FOUNDER(S) of the company. Identification is grounded in a
       Tavily web lookup first (so obscure companies the LLM has never heard of
       are still resolved to real names), then an LLM extracts the founding team
       and industry from that evidence.
    2. Research those founders via the Tavily MCP across several dimensions:
       founder backgrounds, previous companies, previous startups, domain
       expertise, execution history, hiring ability, storytelling, resilience,
       social proof, and social-media activity on X (Twitter) and LinkedIn
       (including how often the founder posts/engages). A focused biography
       search is also run for each individual founder.
    3. An LLM synthesizes the evidence into a structured signal that includes a
       per-founder biography (previous companies, education, previous startups,
       domain-expertise years) and a social-media activity summary.
    4. Tavily image search downloads a headshot for each founder to
       ``committee/founder_images/<company>/`` for use in the investment memo deck.
"""

import json
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress

from committee.tools.tavily_founder_images import fetch_and_store_founder_image
from committee.tools.tavily_mcp import tavily_search

logger = logging.getLogger("committee.founder_analyzer")

# Max characters of evidence to keep per search dimension (keeps the prompt
# focused and within context limits).
_MAX_EVIDENCE_CHARS_PER_DIMENSION = 2500


class FounderIdentification(BaseModel):
    """The founder(s) of a company, used to seed the research."""

    founders: list[str] = Field(description="The founding team's full names, e.g. ['Patrick Collison', 'John Collison']. Used as the search subject.")
    industry: str = Field(description="The industry/domain the company operates in, e.g. 'payments infrastructure'. Used to focus domain-expertise searches.")


class SocialMediaActivity(BaseModel):
    """The founder(s)' presence and posting cadence on social platforms."""

    x_handle: str = Field(default="", description="The founder's X (Twitter) handle if known, e.g. '@patrickc'.")
    x_activity: str = Field(default="", description="Summary of the founder's X (Twitter) activity: what they post about and engagement.")
    linkedin_activity: str = Field(default="", description="Summary of the founder's LinkedIn activity: posts, updates, and engagement.")
    posting_frequency: str = Field(default="", description="How often the founder posts/engages overall, e.g. 'daily', 'a few times a month', 'rarely'.")


class FounderBiography(BaseModel):
    """Structured biography of a single founder, grounded in the research."""

    name: str = Field(default="", description="The founder's full name.")
    role: str = Field(default="", description="The founder's role at the company, e.g. 'Co-founder & CEO'.")
    previous_companies: list[str] = Field(default_factory=list, description="Companies this founder previously worked at (employers), most relevant first.")
    education: list[str] = Field(default_factory=list, description="Schools and degrees, e.g. ['MIT - BS Computer Science'].")
    previous_startups: list[str] = Field(default_factory=list, description="Startups this founder previously founded or co-founded, with outcome if known.")
    domain_expertise_years: float = Field(default=0.0, description="Approximate years of experience this founder has in the company's domain.")
    summary: str = Field(default="", description="Short narrative biography of this founder.")
    image_path: str = Field(default="", description="Local path to the founder's downloaded headshot.")
    image_url: str = Field(default="", description="Source image URL from Tavily.")

    @field_validator("domain_expertise_years", mode="before")
    @classmethod
    def _non_negative_years(cls, v) -> float:
        try:
            return round(max(0.0, float(v)), 1)
        except (TypeError, ValueError):
            return 0.0


class FounderAnalysis(BaseModel):
    """Structured output requested from the LLM."""

    founder_score: float = Field(description="Strength of the founding team on a 0-10 scale (10 = exceptional).")
    confidence: float = Field(description="Confidence in the assessment from 0.0 to 1.0.")
    reasoning: str = Field(description="Concise justification grounded in the gathered evidence.")
    biographies: list[FounderBiography] = Field(default_factory=list, description="One biography per founder: name, role, previous companies, education, previous startups, and domain-expertise years.")
    social_media: SocialMediaActivity = Field(default_factory=SocialMediaActivity, description="Founders' social-media activity on X and LinkedIn and how often they post.")
    data: dict = Field(default_factory=dict, description="Data about the founders, their backgrounds, and track record. Any kind of quantitive data")


class FounderAnalyzerOutput(BaseModel):
    """Verified, final output of the Founder Analyzer agent.

    This model enforces the output contract after the agent runs: scores are
    clamped to their valid ranges, reasoning is non-empty, and all context
    fields are present. Constructing it validates the agent's result before it
    is stored in state or returned to the chat layer.
    """

    company: str = Field(min_length=1)
    founders: str = Field(min_length=1)
    founder_score: float = Field(ge=0.0, le=10.0, description="Founding team strength, 0-10.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence, 0.0-1.0.")
    reasoning: str = Field(min_length=1)
    biographies: list[FounderBiography] = Field(default_factory=list, description="One biography per founder: name, role, previous companies, education, previous startups, and domain-expertise years.")
    social_media: SocialMediaActivity = Field(default_factory=SocialMediaActivity, description="Founders' social-media activity on X and LinkedIn and how often they post.")
    data: dict = Field(default_factory=dict, description="Data about the founders, their backgrounds, and track record. Any kind of quantitive data")

    @field_validator("founder_score", mode="before")
    @classmethod
    def _clamp_founder_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, float(v))), 2)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return round(max(0.0, min(1.0, float(v))), 2)

    @field_validator("company", "founders", "reasoning", mode="before")
    @classmethod
    def _strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


def _lookup_founder_evidence(company: str, agent_id: str, status_label: str) -> str:
    """Run a Tavily lookup for the company's founders/leadership team.

    This grounds identification in live web data so the LLM does not have to
    rely on prior knowledge for companies it has never seen.
    """
    query = f"{company} founders co-founders CEO leadership team about"
    progress.update_status(agent_id, status_label, "Looking up founders")
    results = tavily_search([query], max_results=5)
    result = results[0] if results else {}
    if not result or "error" in result:
        return ""
    return _summarize_result(result.get("result", ""))


def _identify_founders(company: str, question: str, founder_evidence: str, state: AgentState, agent_id: str) -> FounderIdentification:
    """Use an LLM to determine the founder(s) and industry of the company.

    Grounded in ``founder_evidence`` (web lookup) so obscure companies resolve to
    real names rather than a placeholder.
    """
    evidence_block = founder_evidence.strip() or "(no web evidence found)"
    prompt = f"""You are a startup research expert on an investment committee.

The committee is evaluating: "{question}"
Company: {company}

Using the WEB EVIDENCE below (and only it for names), identify the FOUNDER(S) of
this company (the founding team) and the INDUSTRY it operates in. Use the exact
full names that appear in the evidence so they can be researched individually
(e.g. company "Stripe" -> founders ["Patrick Collison", "John Collison"],
industry "payments infrastructure"). Do NOT invent names. If the evidence does
not name any founder, return an empty founders list.

=== WEB EVIDENCE (about {company}) ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "founders": ["<full name of founder>", "<optional additional founder>"],
  "industry": "<industry/domain the company operates in>"
}}
"""
    return call_llm(
        prompt=prompt,
        pydantic_model=FounderIdentification,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: FounderIdentification(
            founders=[],
            industry="Unknown",
        ),
    )


def _search_dimensions(founders: str, company: str, industry: str) -> dict[str, str]:
    """Return the founder research queries to run (leaning on the requested sources)."""
    return {
        "founder_backgrounds": f"{founders} {company} founder background education degree university career history LinkedIn",
        "previous_companies": f"{founders} previous employers companies worked at career history",
        "previous_startups": f"{founders} previous startups companies founded exits acquisitions",
        "domain_expertise": f"{founders} {industry} domain expertise years of experience",
        "execution_history": f"{founders} execution track record products shipped milestones",
        "hiring_ability": f"{founders} team building hiring executives talent",
        "storytelling": f"{founders} interviews podcasts keynote vision narrative",
        "resilience": f"{founders} setbacks failures pivots comeback resilience",
        "social_proof": f"{founders} GitHub patents awards endorsements recognition",
        "x_activity": f"{founders} X Twitter profile posts tweets how often active followers engagement",
        "linkedin_activity": f"{founders} LinkedIn profile posts updates how often active followers engagement",
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


def _build_evidence(founders: str, company: str, industry: str, agent_id: str, status_label: str) -> tuple[dict[str, str], list[dict]]:
    """Run all founder searches.

    Returns a ``(evidence, search_log)`` tuple where ``evidence`` maps each
    dimension to summarized text and ``search_log`` records the query and a
    preview of the result for each dimension (for display/logging).
    """
    dimensions = _search_dimensions(founders, company, industry)
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


def _build_per_founder_evidence(founders_list: list[str], company: str, agent_id: str, status_label: str) -> tuple[dict[str, str], list[dict]]:
    """Run a focused biography search for each individual founder.

    Returns ``(evidence, search_log)`` where evidence is keyed by
    ``"bio: <name>"`` so the synthesis prompt can attribute facts to the right
    person.
    """
    evidence: dict[str, str] = {}
    search_log: list[dict] = []

    for name in founders_list:
        query = f"{name} {company} biography education previous companies startups career"
        progress.update_status(agent_id, status_label, f"Researching founder: {name}")
        results = tavily_search([query], max_results=4)
        result = results[0] if results else {}
        if not result or "error" in result:
            summary = f"(search failed: {result.get('error', 'no result') if result else 'no result'})"
        else:
            summary = _summarize_result(result.get("result", ""))
        evidence[f"bio: {name}"] = summary
        search_log.append(
            {
                "dimension": f"biography:{name}",
                "query": query,
                "result_preview": summary[:800],
            }
        )

    return evidence, search_log


def _attach_founder_images(
    biographies: list[FounderBiography],
    company: str,
    agent_id: str,
    status_label: str,
) -> tuple[list[FounderBiography], list[dict]]:
    """Fetch founder headshots via Tavily and attach local paths to each biography."""
    image_log: list[dict] = []
    updated: list[FounderBiography] = []

    for bio in biographies:
        name = bio.name.strip()
        if not name:
            updated.append(bio)
            continue
        progress.update_status(agent_id, status_label, f"Founder photo: {name}")
        local_path, source_url, log_entry = fetch_and_store_founder_image(name, company)
        image_log.append(log_entry)
        updated.append(
            bio.model_copy(
                update={
                    "image_path": local_path,
                    "image_url": source_url,
                }
            )
        )

    return updated, image_log


def _build_prompt(company: str, founders: str, industry: str, question: str, evidence: dict[str, str]) -> str:
    evidence_block = "\n\n".join(
        f"## {dimension.replace('_', ' ').upper()}\n{text}" for dimension, text in evidence.items()
    )
    return f"""You are a founder analyst on an investment committee evaluating: "{question}"

Company under consideration: {company}
Founder(s): {founders}
Industry: {industry}

The web research below is about the FOUNDER(S). Using ONLY this evidence, assess
the strength of the founding team. Consider founder backgrounds, previous
companies, previous startups, domain expertise, execution history, hiring
ability, storytelling, resilience, social proof, and social-media activity on X
(Twitter) and LinkedIn (including how often the founder posts/engages).

Be skeptical and evidence-based. If evidence is thin or conflicting, lower your
confidence. A great founding team has deep domain expertise, prior successful
exits, a strong execution track record, the ability to attract top talent,
compelling storytelling, demonstrated resilience, and credible social proof.

Compile a BIOGRAPHY for EACH individual founder from the evidence (their name,
role, previous companies, education, previous startups, and approximate years of
domain expertise). The evidence sections labelled "BIO: <name>" are specific to
that founder -- attribute facts to the right person. Also summarize the
founders' SOCIAL-MEDIA activity on X and LinkedIn and how often they post. Leave
a field empty/zero if the evidence does not support it -- do not invent facts.

=== WEB RESEARCH EVIDENCE (about the founder(s): {founders}) ===
{evidence_block}
=== END EVIDENCE ===

Respond in JSON format with EXACTLY these keys:
{{
  "founder_score": <float 0-10, founding team strength>,
  "confidence": <float 0.0-1.0, your confidence in this assessment>,
  "reasoning": "<2-4 sentences citing the strongest evidence>",
  "biographies": [
    {{
      "name": "<founder full name>",
      "role": "<their role, e.g. 'Co-founder & CEO'>",
      "previous_companies": ["<company this founder worked at>", "..."],
      "education": ["<school - degree>", "..."],
      "previous_startups": ["<startup founded, with outcome if known>", "..."],
      "domain_expertise_years": <number, approximate years of experience in {industry}>,
      "summary": "<short narrative biography of this founder>"
    }}
  ],
  "social_media": {{
    "x_handle": "<@handle or empty>",
    "x_activity": "<what the founders post about on X and engagement>",
    "linkedin_activity": "<their LinkedIn posting/activity>",
    "posting_frequency": "<how often they post overall, e.g. 'daily', 'monthly', 'rarely'>"
  }},
  "data": {{"<metric name>": "<quantitative or source-backed fact, e.g. prior exits, years of experience, follower count>"}}
}}
"""


def founder_analyzer_agent(state: AgentState, agent_id: str = "founder_analyzer_agent"):
    """Identify the company's founders, research them, and produce a signal."""
    data = state.get("data", {})
    company = data.get("company")
    question = data.get("question", f"Should we invest in {company}?")

    # Step 1: identify the founder(s) and industry, grounded in a web lookup.
    progress.update_status(agent_id, company, "Identifying founders")
    founder_evidence = _lookup_founder_evidence(company, agent_id, company)
    identification = _identify_founders(company, question, founder_evidence, state, agent_id)
    founders_list = identification.founders or []
    founders = ", ".join(founders_list) if founders_list else "Unknown"
    industry = identification.industry or "Unknown"
    status_label = f"{company} -> {founders}"

    # Step 2: research the founding team collectively, then each founder individually.
    progress.update_status(agent_id, status_label, "Gathering founder evidence")
    evidence, search_log = _build_evidence(founders, company, industry, agent_id, status_label)
    if founders_list:
        bio_evidence, bio_search_log = _build_per_founder_evidence(founders_list, company, agent_id, status_label)
        evidence.update(bio_evidence)
        search_log.extend(bio_search_log)

    progress.update_status(agent_id, status_label, "Synthesizing founder assessment")
    prompt = _build_prompt(company, founders, industry, question, evidence)

    analysis = call_llm(
        prompt=prompt,
        pydantic_model=FounderAnalysis,
        agent_name=agent_id,
        state=state,
        default_factory=lambda: FounderAnalysis(
            founder_score=0.0,
            confidence=0.0,
            reasoning="Unable to analyze the founders due to an error gathering or synthesizing evidence.",
            data={},
        ),
    )

    # If the LLM returned no per-founder biographies, seed one per identified
    # founder so the structured biography is never empty when founders are known.
    if not analysis.biographies and founders_list:
        analysis.biographies = [FounderBiography(name=name) for name in founders_list]

    biographies_with_images, image_log = _attach_founder_images(
        analysis.biographies,
        company,
        agent_id,
        status_label,
    )
    analysis.biographies = biographies_with_images
    search_log.extend(image_log)

    # Reconcile the founders field with the names discovered during research:
    # the synthesis step often resolves founders the up-front identification
    # could not (e.g. obscure companies), so prefer the researched names.
    researched_names = [bio.name.strip() for bio in analysis.biographies if bio.name and bio.name.strip()]
    if researched_names:
        founders_display = ", ".join(researched_names)
    elif founders_list:
        founders_display = founders
    else:
        founders_display = "Unknown"

    # Verify the agent's output against the Pydantic contract (range checks,
    # clamping, non-empty fields) before it leaves the agent.
    progress.update_status(agent_id, status_label, "Verifying output")
    try:
        verified = FounderAnalyzerOutput(
            company=company,
            founders=founders_display,
            founder_score=analysis.founder_score,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            biographies=analysis.biographies,
            social_media=analysis.social_media,
            data=analysis.data,
        )
    except ValidationError as exc:
        logger.warning("Founder analyzer output failed verification: %s", exc)
        verified = FounderAnalyzerOutput(
            company=company or "Unknown",
            founders=founders_display or "Unknown",
            founder_score=0.0,
            confidence=0.0,
            reasoning="Output failed validation; defaulting to a neutral, zero-confidence assessment.",
        )

    result = verified.model_dump()

    if "analysis" not in state["data"]:
        state["data"]["analysis"] = {}
    state["data"]["analysis"]["founder_analyzer"] = result

    # Record the search log so the chat layer can display the queries + results.
    state["data"].setdefault("search_log", {})["founder_analyzer"] = search_log

    progress.update_status(agent_id, status_label, "Done", analysis=json.dumps(result, indent=2))

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(result, "Founder Analyzer Agent")

    # Surface the detected founders/industry in the search log header too.
    search_log.insert(
        0,
        {
            "dimension": "identification",
            "query": f"(web + LLM) founders for {company}",
            "result_preview": f"founders: {founders_display} | industry: {industry}",
        },
    )
    state["data"]["search_log"]["founder_analyzer"] = search_log

    message = HumanMessage(content=json.dumps(result), name=agent_id)

    return {
        "messages": [message],
        "data": state["data"],
    }
