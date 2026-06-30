"""Manual test script for Tavily-based competitor analysis (mirrors the agent flow).

Usage (from ai-hedge-fund):

    poetry run python scripts/test_tavily_competitors.py
    poetry run python scripts/test_tavily_competitors.py "Gamma"
    poetry run python scripts/test_tavily_competitors.py "Nevis Wealth"
"""

import os
import sys

from dotenv import load_dotenv

here = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(here)
project_root = os.path.dirname(repo_root)

load_dotenv(os.path.join(repo_root, ".env"))
load_dotenv(os.path.join(project_root, ".env"), override=True)

sys.path.insert(0, repo_root)

from committee.agents.competitive_intelligence import (  # noqa: E402
    ComparisonTableSpec,
    CompetitiveSynthesis,
    _build_comparison_table,
    _build_synthesis_prompt,
    _identify_product_and_competitors,
)
from committee.tools.tavily_competitors import (  # noqa: E402
    TOP_COMPETITORS,
    gather_competitor_landscape,
    gather_company_metrics,
    gather_product_evidence,
)
from src.utils.llm import call_llm, get_default_model_config  # noqa: E402


def _print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _llm_state() -> dict:
    model_name, model_provider = get_default_model_config()
    return {
        "data": {},
        "metadata": {
            "model_name": model_name,
            "model_provider": model_provider,
        },
    }


def main() -> None:
    company = sys.argv[1] if len(sys.argv) > 1 else "Gamma"
    question = f"Should we invest in {company}?"

    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        print("ERROR: TAVILY_API_KEY is not set.")
        print("Add it to ai-hedge-fund/.env or Summit Project/.env")
        sys.exit(1)

    print(f"API key present: {key[:8]}...{key[-4:]}")
    print(f"Company: {company}")

    evidence: dict[str, str] = {}

    _print_section("Tavily: product research")
    product_evidence, _ = gather_product_evidence(company)
    evidence.update(product_evidence)
    for dim, text in product_evidence.items():
        print(f"\n--- {dim} ---")
        print(text[:600] + ("..." if len(text) > 600 else ""))

    _print_section("Tavily: competitor landscape")
    landscape_evidence, _ = gather_competitor_landscape(company, company, "software")
    evidence.update(landscape_evidence)
    for dim, text in landscape_evidence.items():
        print(f"\n--- {dim} ---")
        print(text[:500] + ("..." if len(text) > 500 else ""))

    _print_section(f"LLM: identify product & top {TOP_COMPETITORS} competitors")
    state = _llm_state()
    identification = _identify_product_and_competitors(company, question, evidence, state, "tavily_competitor_finder")
    product = identification.product_name or company
    category = identification.category or "Unknown"
    is_saas = identification.is_saas
    competitors = list(dict.fromkeys(identification.competitors))[:TOP_COMPETITORS]

    print(f"Product: {product}")
    print(f"Category: {category}")
    print(f"Is SaaS: {is_saas}")
    print(f"Competitors: {competitors}")

    if len(competitors) < TOP_COMPETITORS:
        refined, _ = gather_competitor_landscape(company, product, category)
        evidence.update(refined)
        identification = _identify_product_and_competitors(company, question, evidence, state, "tavily_competitor_finder")
        product = identification.product_name or product
        category = identification.category or category
        is_saas = identification.is_saas
        competitors = list(dict.fromkeys(identification.competitors))[:TOP_COMPETITORS]
        print(f"Refined competitors: {competitors}")

    _print_section("Tavily: per-company metrics")
    for name in [company] + competitors:
        metrics, _ = gather_company_metrics(name, category, include_arr=is_saas)
        evidence.update(metrics)
        print(f"\n--- {name} ---")
        for dim, text in metrics.items():
            print(f"  {dim}: {text[:200]}...")

    _print_section("LLM: synthesis & comparison table")
    synthesis_prompt = _build_synthesis_prompt(
        company, product, category, question, is_saas, competitors, evidence
    )
    synthesis = call_llm(
        prompt=synthesis_prompt,
        pydantic_model=CompetitiveSynthesis,
        agent_name="tavily_competitor_finder",
        state=state,
        default_factory=lambda: CompetitiveSynthesis(
            competitive_score=0.0,
            confidence=0.0,
            reasoning="Synthesis failed.",
            comparison_table=ComparisonTableSpec(),
        ),
    )

    markdown_table = _build_comparison_table(synthesis.comparison_table, is_saas=is_saas)
    print(f"\nScore: {synthesis.competitive_score}/10 | Confidence: {synthesis.confidence}")
    print(f"Reasoning: {synthesis.reasoning}")
    print(f"\n{markdown_table}")


if __name__ == "__main__":
    main()
