"""Chat entry point for the investment committee.

Run from the ai-hedge-fund repo root:

    poetry run python -m committee.main

Ask a question like "should we invest in Stripe?" and the committee's agents
will research and return a structured assessment.
"""

import json
import logging
import os
import re
from urllib.parse import urlparse

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.graph.state import AgentState  # noqa: F401  (kept for type clarity)
from src.utils.llm import call_llm
from src.utils.progress import progress

from committee.graph import build_committee
from committee.agents.investment_memo import investment_memo_agent


def _configure_logging() -> str:
    """Send Tavily search logs to a file (avoids clobbering the live progress UI).

    Set COMMITTEE_LOG_CONSOLE=1 to also stream the logs to stderr in real time.
    Returns the log file path.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    log_path = os.path.join(repo_root, "committee_search.log")

    committee_logger = logging.getLogger("committee")
    committee_logger.setLevel(logging.INFO)
    committee_logger.handlers.clear()
    committee_logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S")

    file_handler = logging.FileHandler(log_path, mode="w")
    file_handler.setFormatter(fmt)
    committee_logger.addHandler(file_handler)

    if os.environ.get("COMMITTEE_LOG_CONSOLE", "").lower() in {"1", "true", "yes"}:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        committee_logger.addHandler(stream_handler)

    return log_path


def _load_env() -> None:
    """Load environment from the ai-hedge-fund/.env and the project root .env."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)  # .../ai-hedge-fund
    project_root = os.path.dirname(repo_root)  # .../Summit Project

    # Load local repo .env first, then the project-root .env (which holds the
    # ANTHROPIC and TAVILY keys). Project-root values win on conflicts.
    load_dotenv(os.path.join(repo_root, ".env"))
    load_dotenv(os.path.join(project_root, ".env"), override=True)


def _model_config() -> tuple[str, str]:
    from src.utils.llm import get_default_model_config

    return get_default_model_config()


def _base_metadata(show_reasoning: bool) -> dict:
    model_name, model_provider = _model_config()
    return {
        "show_reasoning": show_reasoning,
        "model_name": model_name,
        "model_provider": model_provider,
    }


class CompanyName(BaseModel):
    company: str = Field(description="The company the user is asking about, or empty string if none.")


def _company_from_url(text: str) -> str | None:
    if not re.match(r"https?://", text.strip(), re.IGNORECASE):
        return None
    host = urlparse(text.strip()).hostname or ""
    base = host.removeprefix("www.").split(".")[0]
    return base.capitalize() if base else None


def _normalize_question(question: str, company: str) -> str:
    if re.match(r"https?://", question.strip(), re.IGNORECASE):
        return f"Should we invest in {company}?"
    return question


def _extract_company(question: str, metadata: dict) -> str:
    """Use the LLM to pull the company name from the question, with a regex fallback."""
    url_company = _company_from_url(question)
    if url_company:
        return url_company

    prompt = (
        "Extract the single company name the user wants an investment decision on. "
        "Return ONLY the company name (no extra words). If none is present, return an empty string.\n\n"
        f"Question: {question}\n\n"
        'Respond in JSON format: {"company": "..."}'
    )
    state = {"data": {}, "metadata": metadata}
    try:
        result = call_llm(prompt, CompanyName, agent_name="company_extractor", state=state)
        company = (result.company or "").strip()
        if company:
            return company
    except Exception:
        pass

    # Regex fallback: text after "invest in" / "in".
    match = re.search(r"invest(?:ing)?\s+in\s+([A-Za-z0-9.\-&' ]+)", question, re.IGNORECASE)
    if match:
        return match.group(1).strip(" ?.!")
    return question.strip(" ?.!")


def analyze_company(question: str, company: str, show_reasoning: bool = False) -> dict:
    """Run the committee workflow for one company and return its result data.

    Returns the workflow ``data`` dict, which contains ``analysis`` (the agent
    signals) and ``search_log`` (the Tavily queries + result previews).
    """
    committee = build_committee()

    progress.start()
    try:
        final_state = committee.invoke(
            {
                "messages": [HumanMessage(content=question)],
                "data": {
                    "question": question,
                    "company": company,
                    "analysis": {},
                },
                "metadata": _base_metadata(show_reasoning),
            }
        )
    finally:
        progress.stop()

    memo_state = {
        "messages": final_state.get("messages", []),
        "data": final_state["data"],
        "metadata": _base_metadata(show_reasoning),
    }
    progress.start()
    try:
        memo_out = investment_memo_agent(memo_state)
        final_state["data"] = memo_out["data"]
    finally:
        progress.stop()

    return final_state["data"]


def _print_search_log(data: dict) -> None:
    """Print the Tavily search queries and result previews for each agent."""
    search_log = data.get("search_log", {})
    if not search_log:
        return
    print("Tavily Search Log:")
    for agent, entries in search_log.items():
        agent_label = agent.replace("_", " ").title()
        for entry in entries:
            print(f"  [{agent_label}] dimension: {entry.get('dimension')}")
            print(f"    query : {entry.get('query')}")
            print(f"    result: {entry.get('result_preview')}")
        print()


def _print_result(company: str, data: dict) -> None:
    print(f"\nInvestment committee assessment for: {company}\n" + "-" * 48)

    _print_search_log(data)

    analysis = data.get("analysis", {})
    produced = False

    market = analysis.get("market_analyzer")
    if market:
        print("Market Analyzer:")
        print(json.dumps(market, indent=2))
        produced = True

    founder = analysis.get("founder_analyzer")
    if founder:
        print("Founder Analyzer:")
        print(json.dumps(founder, indent=2))
        produced = True

    product = analysis.get("product_analyst")
    if product:
        print("Product Analyst:")
        print(json.dumps(product, indent=2))
        produced = True

    competitive = analysis.get("competitive_intelligence")
    if competitive:
        print("Competitive Intelligence:")
        print(json.dumps(competitive, indent=2))
        produced = True

    risk = analysis.get("risk_analyst")
    if risk:
        print("Risk Analyst:")
        print(json.dumps(risk, indent=2))
        produced = True

    memo = analysis.get("investment_memo")
    if memo:
        print("Investment Memo:")
        print(json.dumps(memo, indent=2))
        if memo.get("presentation_url"):
            print(f"\n(PDF: {memo['presentation_url']})\n")
        if memo.get("edit_path"):
            print(f"(Edit in Presenton: {memo['edit_path']})\n")
        produced = True

    if not produced:
        print("No analysis was produced.")
    print("-" * 48 + "\n")


def main() -> None:
    _load_env()
    log_path = _configure_logging()
    show_reasoning = os.environ.get("COMMITTEE_SHOW_REASONING", "").lower() in {"1", "true", "yes"}
    metadata = _base_metadata(show_reasoning)

    print("Investment Committee  (type 'exit' or 'quit' to leave)")
    print('Ask something like: "Should we invest in Stripe?"')
    print(f"(Tavily search logs are written to {log_path})")
    print(f"(Memo consolidated analysis: committee_memo_consolidated.log)\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            print("Goodbye.")
            break

        company = _extract_company(question, metadata)
        if not company:
            print("I couldn't identify a company in that question. Try: 'Should we invest in Stripe?'\n")
            continue

        question = _normalize_question(question, company)
        data = analyze_company(question, company, show_reasoning=show_reasoning)
        _print_result(company, data)


if __name__ == "__main__":
    main()
