"""Deck Agent — consolidates an uploaded pitch deck into committee-relevant intel.

Given the text extracted from a founder's pitch deck (see ``committee/deck_extract.py``),
this agent pulls out the concrete, investment-relevant data the committee needs —
much of it non-public (traction metrics, the raise, use of funds, roadmap) that
the analysts' web research can't surface — and hands a structured consolidation
to the investment memo agent to fold into the final memo.

It reports the company's OWN claims (management assertions from the deck), and,
because it also sees the committee's independent research, it highlights what the
deck ADDS beyond that research and flags what the deck does not disclose. Like the
rest of the pipeline it goes through ``call_llm`` (retries, structured output,
safe defaults) and is fail-soft.
"""

import json
import logging

from pydantic import BaseModel, Field

from src.utils.llm import call_llm
from src.utils.progress import progress

logger = logging.getLogger("committee.deck_agent")

# The agent's live/streaming id. Kept in sync with the ``deck_intel`` analysis key
# (frontend rebuilds the card id as ``deck_intel_agent`` on reload).
DECK_AGENT_ID = "deck_intel_agent"

# Cap the deck text sent to the LLM so a long deck can't blow the prompt budget.
MAX_DECK_CHARS = 24000

# The committee analyst blocks we summarize as context, so the deck agent can
# tell what the deck ADDS beyond the committee's independent web research.
_ANALYST_KEYS = (
    "market_analyzer",
    "founder_analyzer",
    "product_analyst",
    "competitive_intelligence",
    "risk_analyst",
)


class DeckIntel(BaseModel):
    """Structured consolidation of a pitch deck for the investment memo."""

    reasoning: str = Field(default="", description="2-4 sentence narrative consolidating what the deck provides for the committee and how it complements the independent research.")
    problem: str = Field(default="", description="The problem the company says it solves.")
    solution: str = Field(default="", description="The product/solution as described in the deck.")
    market: str = Field(default="", description="Market size/growth/timing AS STATED in the deck (TAM/SAM/SOM, CAGR). 'Not disclosed' if absent.")
    traction: list[str] = Field(default_factory=list, description="Concrete traction metrics stated in the deck (revenue, users, growth, retention, pilots, logos) — one per item.")
    business_model: str = Field(default="", description="How the company makes or plans to make money, per the deck.")
    team: list[str] = Field(default_factory=list, description="Founders/key team and their stated backgrounds — one per item.")
    competition: list[str] = Field(default_factory=list, description="Competitors or alternatives named in the deck.")
    the_ask: str = Field(default="", description="The raise: round, amount, valuation, and use of funds, as stated. 'Not disclosed' if absent.")
    financials: list[str] = Field(default_factory=list, description="Financial figures stated (revenue, ARR, burn, projections) — one per item.")
    deck_provides: list[str] = Field(default_factory=list, description="Specific data points the deck provides that public web research typically CANNOT (internal metrics, the ask, use of funds, roadmap) — one per item.")
    gaps: list[str] = Field(default_factory=list, description="Important investment questions the deck does NOT answer — one per item.")


def _committee_context(analysis: dict | None) -> str:
    """A compact summary of the committee's findings, so the deck agent can call
    out what the deck adds vs. what independent research already covered."""
    if not analysis:
        return "(committee research not available)"
    parts: list[str] = []
    for key in _ANALYST_KEYS:
        block = analysis.get(key)
        if isinstance(block, dict):
            reasoning = (block.get("reasoning") or "").strip()
            if reasoning:
                parts.append(f"- {key.replace('_', ' ').title()}: {reasoning[:400]}")
    return "\n".join(parts) or "(committee research not available)"


def _build_prompt(company: str, deck_text: str, analysis: dict | None) -> str:
    return (
        "You are the Deck Agent for an AI investment committee. A pitch/investor "
        "deck for the company below was uploaded. Consolidate the deck into the "
        "concrete, investment-relevant data the committee needs.\n\n"
        f"Company: {company}\n\n"
        "The committee has ALSO independently researched this company from public "
        "web sources (summary below). Your job is to capture what the DECK says — "
        "the company's own claims — and especially the specifics the deck provides "
        "that public research usually cannot (internal traction metrics, the raise, "
        "use of funds, roadmap). Report only what the deck states; use 'Not "
        "disclosed' where the deck is silent. Do NOT invent numbers.\n\n"
        "=== COMMITTEE RESEARCH (for context — what is already known) ===\n"
        f"{_committee_context(analysis)}\n"
        "=== END COMMITTEE RESEARCH ===\n\n"
        "=== UPLOADED DECK TEXT ===\n"
        f"{deck_text[:MAX_DECK_CHARS]}\n"
        "=== END DECK TEXT ===\n\n"
        "Respond in JSON with EXACTLY these keys:\n"
        "{\n"
        '  "reasoning": "<2-4 sentences on what the deck provides for the committee>",\n'
        '  "problem": "<problem the company solves>",\n'
        '  "solution": "<product/solution>",\n'
        '  "market": "<market size/growth as stated, or \'Not disclosed\'>",\n'
        '  "traction": ["<metric>", "..."],\n'
        '  "business_model": "<how it makes money>",\n'
        '  "team": ["<founder — background>", "..."],\n'
        '  "competition": ["<competitor>", "..."],\n'
        '  "the_ask": "<round, amount, valuation, use of funds, or \'Not disclosed\'>",\n'
        '  "financials": ["<figure>", "..."],\n'
        '  "deck_provides": ["<data point web research can\'t give>", "..."],\n'
        '  "gaps": ["<question the deck does not answer>", "..."]\n'
        "}"
    )


def run_deck_agent(
    deck_text: str,
    company: str,
    analysis: dict | None = None,
    metadata: dict | None = None,
    agent_id: str = DECK_AGENT_ID,
) -> dict:
    """Consolidate the uploaded deck into a ``DeckIntel`` dict for the memo agent.

    ``analysis`` is the committee's consolidated output (used as context so the
    agent can highlight what the deck adds). Fail-soft: returns a minimal result
    if the deck text is empty or the LLM call fails.
    """
    company = company or "the company"
    if not (deck_text or "").strip():
        return DeckIntel(reasoning="No deck text was available to consolidate.").model_dump()

    progress.update_status(agent_id, company, "Reading the uploaded deck")
    prompt = _build_prompt(company, deck_text, analysis)
    progress.update_status(agent_id, company, "Consolidating deck data for the committee")

    result = call_llm(
        prompt=prompt,
        pydantic_model=DeckIntel,
        agent_name=agent_id,
        state={"data": {}, "metadata": metadata or {}},
        default_factory=lambda: DeckIntel(
            reasoning="The deck could not be consolidated into structured data; the memo will rely on committee research.",
        ),
    )
    out = result.model_dump()
    progress.update_status(agent_id, company, "Done", analysis=json.dumps(out, indent=2))
    return out
