"""Investment Memo Agent.

Consolidates outputs from all committee analyst agents, uses an LLM to draft an
investment-memo slide deck, and generates a PDF presentation via Presenton.
"""

import json
import logging
import os
import re
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm, get_memo_max_tokens
from src.utils.progress import progress

from committee.tools.presenton_api import extract_edit_path, extract_presentation_url, generate_presentation, upload_image

logger = logging.getLogger("committee.investment_memo")
_consolidated_logger = logging.getLogger("committee.investment_memo.consolidated")
_consolidated_log_configured = False

_ANALYST_KEYS = (
    "market_analyzer",
    "founder_analyzer",
    "product_analyst",
    "competitive_intelligence",
    "risk_analyst",
)


class MemoBodySlide(BaseModel):
    heading: str = Field(description="Slide title, e.g. 'Market Opportunity'.")
    content: str = Field(
        description="Expanded investment-analyst prose with bullets, metrics, and synthesis grounded in the committee data."
    )


class InvestmentRecommendation(BaseModel):
    decision: Literal["invest", "pass", "watchlist"]
    investment_amount_usd_millions: float | None = Field(
        default=None,
        description="Proposed check size in USD millions when decision is invest.",
    )
    headline: str = Field(
        description="One-line recommendation headline, e.g. 'Invest with $15M', 'Pass', or 'Watchlist'.",
    )
    rationale: str = Field(description="2-4 sentences supporting the recommendation.")


class InvestmentMemoContent(BaseModel):
    subtitle: str = Field(description="Subtitle for the title slide, e.g. 'Series B SaaS — Investment Committee Memo'.")
    body_slides: list[MemoBodySlide] = Field(
        description="Exactly 6 substantive slides between the title slide and final recommendation slide.",
    )
    recommendation: InvestmentRecommendation


class InvestmentMemoOutput(BaseModel):
    company: str = Field(min_length=1)
    question: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    recommendation_headline: str = Field(min_length=1)
    slide_count: int = Field(ge=2)
    slides_preview: list[str] = Field(default_factory=list)
    presentation_url: str = Field(default="")
    edit_path: str = Field(default="")
    presenton_response: dict = Field(default_factory=dict)
    founder_images: list[dict] = Field(default_factory=list)

    @field_validator("company", "question", "recommendation", "recommendation_headline", mode="before")
    @classmethod
    def _strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


def _agent_input_snapshot(data: dict) -> dict:
    """Structured view of everything passed into the investment memo agent."""
    analysis = data.get("analysis", {})
    return {
        "company": data.get("company"),
        "question": data.get("question"),
        "analyst_outputs": {key: analysis[key] for key in _ANALYST_KEYS if key in analysis},
        "search_log_agents": list(data.get("search_log", {}).keys()),
    }


def print_agent_inputs(data: dict) -> None:
    """Print the consolidated inputs passed to the investment memo agent."""
    snapshot = _agent_input_snapshot(data)
    print("\n" + "=" * 48)
    print("Investment Memo Agent — Inputs")
    print("=" * 48)
    print(json.dumps(snapshot, indent=2))
    print("=" * 48 + "\n")
    logger.info("Investment memo agent inputs:\n%s", json.dumps(snapshot, indent=2))


def _consolidated_log_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    return os.path.join(repo_root, "committee_memo_consolidated.log")


def _configure_consolidated_log_file() -> str:
    """Attach a dedicated file handler for the memo LLM consolidated analysis block."""
    global _consolidated_log_configured
    log_path = _consolidated_log_path()
    if not _consolidated_log_configured:
        _consolidated_logger.setLevel(logging.INFO)
        _consolidated_logger.handlers.clear()
        _consolidated_logger.propagate = False
        handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        _consolidated_logger.addHandler(handler)
        _consolidated_log_configured = True
    return log_path


def log_consolidated_analysis_payload(company: str, question: str, analysis: dict) -> str:
    """Write the exact analyst block embedded in the memo LLM prompt to a separate log file."""
    log_path = _configure_consolidated_log_file()
    payload = _consolidated_analysis_payload(analysis)
    _consolidated_logger.info(
        "Investment memo consolidated analysis\n"
        "company: %s\n"
        "question: %s\n"
        "%s\n"
        "%s\n"
        "%s",
        company,
        question,
        "=" * 60,
        payload,
        "=" * 60,
    )
    return log_path


_FOUNDER_SLIDE_KEYWORDS = ("founder", "founding team", "leadership", "management team", "team")


def _collect_founder_images(analysis: dict) -> list[dict[str, str]]:
    founder = analysis.get("founder_analyzer") or {}
    images: list[dict[str, str]] = []
    for bio in founder.get("biographies") or []:
        if not isinstance(bio, dict):
            continue
        local_path = (bio.get("image_path") or "").strip()
        name = (bio.get("name") or "").strip()
        if not local_path or not name or not os.path.isfile(local_path):
            continue
        images.append(
            {
                "name": name,
                "role": (bio.get("role") or "").strip(),
                "local_path": local_path,
                "source_url": (bio.get("image_url") or "").strip(),
            }
        )
    return images


def _upload_founder_images_for_presenton(founder_images: list[dict[str, str]]) -> list[dict[str, str]]:
    uploaded: list[dict[str, str]] = []
    for item in founder_images:
        try:
            asset = upload_image(item["local_path"])
            presenton_url = asset.get("url") or asset.get("path") or ""
            if not presenton_url:
                logger.warning("Presenton image upload returned no URL for %s", item["local_path"])
                continue
            uploaded.append({**item, "presenton_url": presenton_url})
        except Exception as exc:
            logger.warning("Failed to upload founder image for %s: %s", item.get("name"), exc)
    return uploaded


def _is_founder_slide(heading: str, content: str) -> bool:
    text = f"{heading} {content}".lower()
    return any(keyword in text for keyword in _FOUNDER_SLIDE_KEYWORDS)


def _format_founder_photo_block(founder_images: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for founder in founder_images:
        url = founder.get("presenton_url")
        if not url:
            continue
        name = founder.get("name", "Founder")
        role = founder.get("role", "")
        caption = f"{name} — {role}" if role else name
        lines.append(f"![{caption}]({url})")
    return "\n\n".join(lines)


def _slim_analyst_block(key: str, block: dict) -> dict:
    """Drop redundant verbose fields before embedding analyst output in the memo prompt."""
    slim = dict(block)
    if key == "competitive_intelligence":
        slim.pop("markdown_table", None)
        slim.pop("markdown_path", None)
    if key == "founder_analyzer" and isinstance(slim.get("biographies"), list):
        slim["biographies"] = [
            {k: bio.get(k) for k in ("name", "role", "summary", "image_path", "image_url")}
            for bio in slim["biographies"][:4]
            if isinstance(bio, dict)
        ]
    return slim


def _consolidated_analysis_payload(analysis: dict) -> str:
    sections: list[str] = []
    for key in _ANALYST_KEYS:
        block = analysis.get(key)
        if block:
            sections.append(f"## {key.replace('_', ' ').title()}\n{json.dumps(_slim_analyst_block(key, block), indent=2)}")
    return "\n\n".join(sections) if sections else "(no analyst outputs available)"


def _deck_intel_payload(analysis: dict) -> str:
    """The Deck Agent's consolidation of an uploaded pitch deck, if present —
    the company's own claims (traction, the ask, use of funds, internal metrics)
    that the committee's web research typically can't surface. Empty string when
    the run wasn't started from an uploaded deck."""
    deck = analysis.get("deck_intel")
    if not isinstance(deck, dict) or not deck:
        return ""
    return json.dumps(deck, indent=2)


def _sanitize_presenton_text(text: str) -> str:
    """Normalize slide copy so Presenton smart-design does not pull out rogue metric callouts."""
    if not text:
        return text

    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        # Preserve markdown image lines for founder photos.
        if line.strip().startswith("!["):
            cleaned_lines.append(line)
            continue

        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\*([^*]+)\*", r"\1", line)
        line = re.sub(r"_([^_]+)_", r"\1", line)
        line = re.sub(r"~\s*\$", "approximately $", line)
        line = re.sub(r"~\s*(\d)", r"approximately \1", line)
        line = re.sub(
            r"\$(\d+(?:\.\d+)?)\s*([MmBbKk])?\s*[–—-]\s*\$?(\d+(?:\.\d+)?)\s*([MmBbKk])?",
            lambda m: (
                f"${m.group(1)}{m.group(2) or ''} to "
                f"${m.group(3)}{(m.group(4) or m.group(2) or '')}"
            ),
            line,
        )
        line = re.sub(r"\s*\+\s*", " and ", line)
        line = re.sub(r"\(\s*", "(", line)
        line = re.sub(r"\s*\)", ")", line)
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _build_memo_prompt(company: str, question: str, analysis: dict) -> str:
    consolidated = _consolidated_analysis_payload(analysis)
    deck_intel = _deck_intel_payload(analysis)
    deck_section = (
        (
            "\n=== PITCH DECK (COMPANY'S OWN CLAIMS, via the Deck Agent) ===\n"
            f"{deck_intel}\n"
            "=== END PITCH DECK ===\n"
        )
        if deck_intel
        else ""
    )
    deck_requirement = (
        (
            "PITCH DECK HANDLING: A PITCH DECK section is present below — it is the company's OWN "
            "claims from an uploaded deck, consolidated by the Deck Agent. Fold its concrete specifics into the "
            "relevant slides — especially data the committee's web research lacks (traction "
            "metrics, the raise/ask, use of funds, internal financials, roadmap). Attribute deck "
            "figures as management's claims (e.g. 'Per the deck: ...'), prefer committee-verified "
            "facts when the two disagree, and explicitly flag material claims the committee could "
            "not corroborate. Weave this in without exceeding 6 body slides.\n"
        )
        if deck_intel
        else ""
    )
    return f"""You are a senior investment analyst preparing an investment committee memo deck.

Investment question: "{question}"
Company: {company}

Using the committee analyst outputs below{" and the uploaded pitch deck" if deck_intel else ""}, draft slide content for an investment memo presentation.

Requirements:
1. Provide a professional subtitle for the title slide.
2. Create exactly 6 body slides that synthesize the committee work. Cover where the evidence supports it:
   - Executive summary / investment thesis
   - Market opportunity (TAM, growth, timing)
   - Product & technology
   - Competitive landscape
   - Founding team
   - Key risks / business model (combine if needed; ground risks in the Risk Analyst
     output — regulatory exposure, key-person risk, market timing, and red flags —
     when that analysis is present)
3. Keep each slide concise: 3-5 bullet points, max ~120 words per slide.
   Do NOT invent facts not supported by the analyst outputs{" or the pitch deck" if deck_intel else ""}. Use "Unknown" or "Not disclosed" when missing.
{deck_requirement}
4. Presenton-safe formatting (critical — prevents broken slide typography):
   - Use plain bullet lines only. No markdown bold/italic, no tildes (~), no em-dashes between figures.
   - Put each metric on its own bullet or a single clear label, e.g. "Revenue: $604.6M" or "Seed round: $5M".
   - NEVER combine amounts inline, e.g. avoid "$40M ($5M Seed + $35M Series A)", "~$500M–1B", or "$5M + $35M".
   - For funding breakdowns use separate bullets: "Total raised: $40M", "Seed: $5M", "Series A: $35M".
   - For competitor lists use "Company — Revenue: $Xm" on one line per competitor.
5. Final recommendation (separate from body slides):
   - decision: "invest", "pass", or "watchlist"
   - If invest, propose a reasonable check size in USD millions based on stage signals in the data
     (use null for amount only if truly insufficient context — prefer a justified estimate or range narrative in rationale)
   - headline: exactly one of:
       * "Invest with $XM" (X = amount in millions)
       * "Pass"
       * "Watchlist"
   - rationale: 2-4 sentences weighing market, product, team, competitive, and risk scores

=== COMMITTEE ANALYST OUTPUTS ===
{consolidated}
=== END OUTPUTS ===
{deck_section}
Respond in JSON format with EXACTLY these keys:
{{
  "subtitle": "<title slide subtitle>",
  "body_slides": [
    {{"heading": "<slide title>", "content": "<expanded analyst content>"}}
  ],
  "recommendation": {{
    "decision": "<invest|pass|watchlist>",
    "investment_amount_usd_millions": <float or null>,
    "headline": "<Invest with $XM | Pass | Watchlist>",
    "rationale": "<supporting rationale>"
  }}
}}
"""


def _format_title_slide(company: str, question: str, subtitle: str) -> str:
    report_date = date.today().strftime("%B %Y")
    return (
        f"Slide 1 — Investment Memo: {company}\n\n"
        f"Company: {company}\n"
        f"Investment Question: {question}\n"
        f"Subtitle: {subtitle}\n"
        f"Report Date: {report_date}\n\n"
        f"Prepared by: Archer — Investment Committee\n"
        f"Confidential — For discussion purposes only"
    )


def _format_recommendation_slide(recommendation: InvestmentRecommendation) -> str:
    amount_line = ""
    if recommendation.decision == "invest" and recommendation.investment_amount_usd_millions is not None:
        amount_line = f"\nProposed Check Size: ${recommendation.investment_amount_usd_millions:g}M\n"
    return (
        f"Slide — Recommendation\n\n"
        f"{recommendation.headline}\n"
        f"{amount_line}\n"
        f"{recommendation.rationale}"
    )


def assemble_presenton_slides(
    company: str,
    question: str,
    memo: InvestmentMemoContent,
    founder_images: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build Presenton slide payloads: title, body slides, recommendation."""
    founder_block = _format_founder_photo_block(founder_images or [])
    founder_slide_index: int | None = None
    if founder_block:
        for index, body in enumerate(memo.body_slides):
            if _is_founder_slide(body.heading, body.content):
                founder_slide_index = index
                break

    slides: list[dict[str, str]] = [
        {"content": _sanitize_presenton_text(_format_title_slide(company, question, memo.subtitle)), "layout": ""},
    ]
    for index, body in enumerate(memo.body_slides, start=2):
        content = _sanitize_presenton_text(f"Slide {index} — {body.heading}\n\n{body.content}")
        if founder_block and founder_slide_index is not None and index - 2 == founder_slide_index:
            content += f"\n\n{founder_block}"
        slides.append({"content": content, "layout": ""})
    slides.append(
        {
            "content": _sanitize_presenton_text(_format_recommendation_slide(memo.recommendation)),
            "layout": "",
        }
    )
    return slides


def investment_memo_agent(state: AgentState, agent_id: str = "investment_memo_agent"):
    """Synthesize analyst outputs into a Presenton investment memo deck."""
    data = state.get("data", {})
    company = data.get("company") or "Unknown"
    question = data.get("question", f"Should we invest in {company}?")
    analysis = data.get("analysis", {})

    print_agent_inputs(data)

    progress.update_status(agent_id, company, "Drafting investment memo slides")
    consolidated_log_path = log_consolidated_analysis_payload(company, question, analysis)
    print(f"(Consolidated analysis logged to {consolidated_log_path})\n")
    prompt = _build_memo_prompt(company, question, analysis)
    print("\n" + "=" * 48)
    print("Investment Memo Agent — LLM Prompt")
    print("=" * 48)
    print(prompt)
    print("=" * 48 + "\n")
    logger.info("Investment memo LLM prompt (%s chars):\n%s", len(prompt), prompt)

    memo_content = call_llm(
        prompt=prompt,
        pydantic_model=InvestmentMemoContent,
        agent_name=agent_id,
        state=state,
        max_tokens=get_memo_max_tokens(),
        default_factory=lambda: InvestmentMemoContent(
            subtitle="Investment Committee Memo",
            body_slides=[
                MemoBodySlide(
                    heading="Committee Summary",
                    content="Insufficient analyst data to produce a full memo. Defaulting to watchlist pending further diligence.",
                )
            ],
            recommendation=InvestmentRecommendation(
                decision="watchlist",
                investment_amount_usd_millions=None,
                headline="Watchlist",
                rationale="Analyst outputs were incomplete; recommend further diligence before a decision.",
            ),
        ),
    )
    print("\n" + "=" * 48)
    print("Investment Memo Agent — LLM Output")
    print("=" * 48)
    print(json.dumps(memo_content.model_dump(), indent=2))
    print("=" * 48 + "\n")

    founder_images = _collect_founder_images(analysis)
    uploaded_founder_images = _upload_founder_images_for_presenton(founder_images)
    presenton_slides = assemble_presenton_slides(
        company,
        question,
        memo_content,
        uploaded_founder_images,
    )

    progress.update_status(agent_id, company, "Generating presentation via Presenton")
    presenton_response: dict = {}
    presentation_url = ""
    edit_path = ""
    try:
        presenton_response = generate_presentation(presenton_slides)
        presentation_url = extract_presentation_url(presenton_response)
        edit_path = extract_edit_path(presenton_response)
    except Exception as exc:
        logger.warning("Presenton generation failed: %s", exc)
        presenton_response = {"error": str(exc)}

    progress.update_status(agent_id, company, "Verifying output")
    try:
        verified = InvestmentMemoOutput(
            company=company,
            question=question,
            recommendation=memo_content.recommendation.decision,
            recommendation_headline=memo_content.recommendation.headline,
            slide_count=len(presenton_slides),
            slides_preview=[s["content"][:200] for s in presenton_slides],
            presentation_url=presentation_url,
            edit_path=edit_path,
            presenton_response=presenton_response,
            founder_images=uploaded_founder_images,
        )
    except ValidationError as exc:
        logger.warning("Investment memo output failed verification: %s", exc)
        verified = InvestmentMemoOutput(
            company=company,
            question=question,
            recommendation=memo_content.recommendation.decision,
            recommendation_headline=memo_content.recommendation.headline,
            slide_count=len(presenton_slides),
            presentation_url=presentation_url,
            presenton_response=presenton_response,
            founder_images=uploaded_founder_images,
        )

    result = verified.model_dump()

    if "analysis" not in state["data"]:
        state["data"]["analysis"] = {}
    state["data"]["analysis"]["investment_memo"] = result

    progress.update_status(agent_id, company, "Done", analysis=json.dumps(result, indent=2))

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(result, "Investment Memo Agent")

    message = HumanMessage(content=json.dumps(result), name=agent_id)

    return {
        "messages": [message],
        "data": state["data"],
    }
