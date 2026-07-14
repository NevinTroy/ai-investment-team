"""Comparative-analysis agent for the investment committee.

Given companies the committee has ALREADY analyzed (their stored analyst output
sitting in Supabase), this agent produces a structured side-by-side comparison —
without re-running any research. It powers two question shapes:

    "Notion vs Airtable"            -> compare two named companies
    "Compare our fintech companies" -> compare every analyzed company in a sector

The heavy lifting (market/founder/product/risk scores) was already done by the
committee and persisted in ``chats.analysis``. This agent's job is ranking and
narrative: read those stored scores, normalize them into one table, pick a
winner, and explain why. It never invents numbers — it reuses the ones the
analysts produced.

Like the rest of the pipeline it goes through ``call_llm`` (retries, structured
output, safe defaults) and is fail-soft: with no usable input it returns an
empty comparison rather than raising.
"""

import json
import logging

from pydantic import BaseModel, Field, field_validator

from src.utils.llm import call_llm

logger = logging.getLogger("committee.comparison_agent")

# The analyst blocks (inside chats.analysis) we surface to the comparison LLM,
# mapped to the dimension label shown in the table.
_DIMENSIONS = {
    "market_analyzer": "Market",
    "founder_analyzer": "Founders",
    "product_analyst": "Product",
    "competitive_intelligence": "Competitive",
    "risk_analyst": "Risk",
}


class CompanyRow(BaseModel):
    """One company's row in the comparison table."""

    company: str = Field(description="The company name.")
    scores: dict = Field(default_factory=dict, description="Dimension label -> numeric score (0-10), drawn from the stored analyst output. Omit a dimension if that analyst didn't run for this company.")
    highlight: str = Field(default="", description="The company's single biggest strength, one short phrase.")
    concern: str = Field(default="", description="The company's single biggest risk/weakness, one short phrase.")

    @field_validator("company", "highlight", "concern", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class ComparisonResult(BaseModel):
    """Structured, table-ready comparison of two or more companies."""

    headline: str = Field(description="A one-line verdict, e.g. 'Airtable edges out Notion on market, loses on defensibility'.")
    winner: str = Field(default="", description="The company that comes out ahead overall, or empty string for a neutral sector overview.")
    rationale: str = Field(description="3-5 sentences explaining the comparison and the verdict, grounded in the scores and findings.")
    dimensions: list[str] = Field(default_factory=list, description="The dimension labels used as the table axis, e.g. ['Market','Founders','Product','Risk'].")
    rows: list[CompanyRow] = Field(default_factory=list, description="One row per company being compared.")


def _company_block(row: dict) -> str:
    """Render one stored analysis into a compact, LLM-readable block: the
    company's available analyst scores + reasoning."""
    company = row.get("company") or "Unknown"
    sector = row.get("sector") or ""
    analysis = row.get("analysis") or {}

    parts = [f"### {company}" + (f"  (sector: {sector})" if sector else "")]
    for key, label in _DIMENSIONS.items():
        block = analysis.get(key)
        if not isinstance(block, dict):
            continue
        # Each analyst uses a different *_score key; surface whichever is present.
        score = next(
            (block[k] for k in block if k.endswith("score") and isinstance(block[k], (int, float))),
            None,
        )
        reasoning = block.get("reasoning") or ""
        score_str = f"{score}" if score is not None else "n/a"
        parts.append(f"- {label} score: {score_str}. {reasoning}".strip())
    return "\n".join(parts)


def _build_prompt(question: str, rows: list[dict]) -> str:
    blocks = "\n\n".join(_company_block(r) for r in rows)
    names = ", ".join(r.get("company") or "Unknown" for r in rows)
    return (
        "You are an investment analyst producing a SIDE-BY-SIDE comparison of "
        "companies the committee has already researched. Below is each company's "
        "stored analyst output (scores on a 0-10 scale plus reasoning).\n\n"
        f'User question: "{question}"\n'
        f"Companies to compare: {names}\n\n"
        "=== STORED ANALYSES ===\n"
        f"{blocks}\n"
        "=== END ANALYSES ===\n\n"
        "Build the comparison using ONLY these findings. Reuse the given scores — "
        "do NOT invent new numbers; if a dimension is missing for a company, omit "
        "it from that company's scores. Choose the dimensions that every (or most) "
        "companies share as the table axis. Pick an overall winner when the "
        "question is a head-to-head ('A vs B'); for a whole-sector overview, you "
        "may leave winner empty and instead rank them in the rationale.\n\n"
        "Respond in JSON with EXACTLY these keys:\n"
        '{"headline": "<one-line verdict>", '
        '"winner": "<company name or empty string>", '
        '"rationale": "<3-5 sentences grounded in the scores/findings>", '
        '"dimensions": ["Market", "Founders", "Product", "Risk"], '
        '"rows": [{"company": "<name>", "scores": {"Market": 8.1, "Founders": 7.5}, '
        '"highlight": "<biggest strength>", "concern": "<biggest risk>"}]}'
    )


def run_comparison_agent(rows: list[dict], question: str, metadata: dict | None = None) -> dict:
    """Compare the given stored analyses and return a ``ComparisonResult`` dict.

    ``rows`` is the output of ``persistence.get_analyses_for_comparison`` — one
    entry per company with its ``analysis`` payload. With fewer than two usable
    companies there is nothing to compare, so an empty result is returned.
    """
    usable = [r for r in rows if isinstance(r.get("analysis"), dict) and r["analysis"]]
    if len(usable) < 2:
        return ComparisonResult(
            headline="Not enough analyzed companies to compare.",
            winner="",
            rationale="A comparison needs at least two companies with completed analyses.",
            dimensions=[],
            rows=[],
        ).model_dump()

    prompt = _build_prompt(question, usable)
    state = {"data": {}, "metadata": metadata or {}}

    def _default() -> ComparisonResult:
        # Fall back to a raw score table assembled directly from stored output,
        # so a failed LLM call still yields a usable side-by-side.
        rows_out = []
        for r in usable:
            analysis = r.get("analysis") or {}
            scores = {}
            for key, label in _DIMENSIONS.items():
                block = analysis.get(key)
                if isinstance(block, dict):
                    score = next(
                        (block[k] for k in block if k.endswith("score") and isinstance(block[k], (int, float))),
                        None,
                    )
                    if score is not None:
                        scores[label] = score
            rows_out.append(CompanyRow(company=r.get("company") or "Unknown", scores=scores))
        return ComparisonResult(
            headline="Comparison of analyzed companies.",
            winner="",
            rationale="A narrative comparison could not be generated; showing the stored analyst scores side by side.",
            dimensions=[_DIMENSIONS[k] for k in _DIMENSIONS],
            rows=rows_out,
        )

    result = call_llm(
        prompt=prompt,
        pydantic_model=ComparisonResult,
        agent_name="comparison_agent",
        state=state,
        default_factory=_default,
    )
    return result.model_dump()


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    from committee.persistence import get_analyses_for_comparison

    _repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(_repo_root / ".env")
    load_dotenv(_repo_root.parent / ".env", override=True)

    logging.basicConfig(level=logging.INFO)
    names = sys.argv[1:] or ["Notion", "Airtable"]
    fetched = get_analyses_for_comparison(companies=names)
    print(f"Fetched {len(fetched)} analyses: {[r.get('company') for r in fetched]}")
    out = run_comparison_agent(fetched, f"Compare {' vs '.join(names)}")
    print(json.dumps(out, indent=2, default=str))
