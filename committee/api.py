"""FastAPI web server for the investment committee.

Run:
    poetry run uvicorn committee.api:app --reload --port 8000
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Load env before importing committee modules that need API keys
_here = Path(__file__).parent
_repo_root = _here.parent
_project_root = _repo_root.parent
load_dotenv(_repo_root / ".env")
load_dotenv(_project_root / ".env", override=True)

from committee.graph import build_committee  # noqa: E402
from committee.agents.investment_memo import investment_memo_agent  # noqa: E402
from committee.main import _base_metadata, _extract_company, _normalize_question  # noqa: E402
from src.utils.progress import progress  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="Investment Committee API")

_executor = ThreadPoolExecutor(max_workers=2)

AGENT_DISPLAY = {
    "market_analyzer_agent": "Market Analyzer",
    "founder_analyzer_agent": "Founder Analyzer",
    "product_analyst_agent": "Product Analyst",
    "competitive_intelligence_agent": "Competitive Intelligence",
    "investment_memo_agent": "Investment Memo",
}

FRONTEND_DIR = _repo_root / "frontend"


class AnalyzeRequest(BaseModel):
    question: str


def _run_analysis(question: str, company: str) -> dict:
    """Blocking analysis — runs in a thread pool executor."""
    committee = build_committee()
    metadata = _base_metadata(False)

    # Suppress the Rich Live display in web-server context (no TTY).
    _orig_start = progress.start
    _orig_stop = progress.stop
    progress.start = lambda: None
    progress.stop = lambda: None

    try:
        final_state = committee.invoke(
            {
                "messages": [HumanMessage(content=question)],
                "data": {
                    "question": question,
                    "company": company,
                    "analysis": {},
                },
                "metadata": metadata,
            }
        )

        memo_state = {
            "messages": final_state.get("messages", []),
            "data": final_state["data"],
            "metadata": metadata,
        }
        memo_out = investment_memo_agent(memo_state)
        final_state["data"] = memo_out["data"]
    finally:
        progress.start = _orig_start
        progress.stop = _orig_stop

    return final_state["data"]


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def handler(agent_name, ticker, status, analysis, timestamp):
        event = json.dumps({
            "type": "agent_update",
            "agent": agent_name,
            "display_name": AGENT_DISPLAY.get(agent_name, agent_name),
            "ticker": ticker or "",
            "status": status,
            "analysis": analysis,
        })
        loop.call_soon_threadsafe(queue.put_nowait, event)

    progress.register_handler(handler)

    metadata = _base_metadata(False)
    company = _extract_company(req.question, metadata)
    question = _normalize_question(req.question, company)

    async def _task():
        try:
            data = await loop.run_in_executor(
                _executor,
                lambda: _run_analysis(question, company),
            )
            await queue.put(json.dumps({"type": "complete", "data": data, "company": company}))
        except Exception as exc:
            logger.exception("Analysis failed")
            await queue.put(json.dumps({"type": "error", "message": str(exc)}))
        finally:
            progress.unregister_handler(handler)
            await queue.put(None)

    asyncio.create_task(_task())

    async def stream():
        # send company name immediately so the UI can show it
        yield f"data: {json.dumps({'type': 'start', 'company': company, 'question': question})}\n\n"
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {item}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index = FRONTEND_DIR / "index.html"
    return HTMLResponse(index.read_text())
