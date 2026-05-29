"""
/backtest — trigger runs, stream progress via SSE, view results.
"""

import asyncio
import json
import logging
import queue
import threading
from typing import AsyncGenerator

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter()
templates: Jinja2Templates = None

# Per-run progress queues: run_id -> queue.Queue
_progress_queues: dict[str, queue.Queue] = {}


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    runner = request.app.state.backtest_runner
    config = request.app.state.config
    runs = runner.list_runs(limit=30)

    return templates.TemplateResponse(
        "backtest.html",
        {
            "request": request,
            "runs": runs,
            "coins": config.TRACKED_COINS,
            "timeframes": ["5m", "15m", "1h", "4h", "1d"],
            "exchanges": ["binance", "kraken", "coinbase", "bybit", "okx"],
        },
    )


@router.post("/backtest/run")
async def start_run(
    request: Request,
    coin: str = Form(...),
    exchange: str = Form(...),
    timeframe: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
):
    runner = request.app.state.backtest_runner
    q: queue.Queue = queue.Queue()

    def progress_cb(event: dict):
        q.put(event)

    def run_in_thread():
        run_id = runner.run(coin, exchange, timeframe, start_date, end_date, progress_cb)
        q.put(None)  # sentinel
        _progress_queues.pop(run_id, None)

    # Generate a placeholder run_id so the SSE endpoint knows where to listen
    # (actual run_id returned by runner.run() is used inside the thread)
    thread = threading.Thread(target=run_in_thread, daemon=True)

    # We need the run_id to create the queue before the thread starts.
    # Solution: capture it via the first progress event.
    captured_id: list[str] = []

    def capturing_cb(event: dict):
        if event.get("type") == "start":
            captured_id.append(event["run_id"])
            _progress_queues[event["run_id"]] = q
        q.put(event)

    def run_capturing():
        runner.run(coin, exchange, timeframe, start_date, end_date, capturing_cb)
        q.put(None)

    thread = threading.Thread(target=run_capturing, daemon=True)
    thread.start()

    # Wait briefly to get the run_id from the first event
    import time
    for _ in range(20):
        if captured_id:
            break
        time.sleep(0.1)

    run_id = captured_id[0] if captured_id else "unknown"
    # Redirect to SSE stream URL so the browser can follow progress
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/backtest/results?highlight={run_id}", status_code=303)


@router.get("/backtest/progress/{run_id}")
async def progress_stream(run_id: str, request: Request) -> StreamingResponse:
    """SSE endpoint: streams progress events for a running backtest."""

    async def event_generator() -> AsyncGenerator[str, None]:
        q = _progress_queues.get(run_id)
        if q is None:
            yield "data: {\"type\": \"error\", \"error\": \"run not found\"}\n\n"
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=1))
                if event is None:
                    yield "data: {\"type\": \"done\"}\n\n"
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/backtest/results", response_class=HTMLResponse)
async def results_list(request: Request, highlight: str = ""):
    runner = request.app.state.backtest_runner
    runs = runner.list_runs(limit=30)
    return templates.TemplateResponse(
        "backtest_results.html",
        {"request": request, "runs": runs, "highlight": highlight},
    )


@router.get("/backtest/results/{run_id}", response_class=HTMLResponse)
async def result_detail(run_id: str, request: Request):
    runner = request.app.state.backtest_runner
    summary = runner.get_summary(run_id)
    trades = runner.get_trades(run_id)
    equity_curve = runner.get_equity_curve(run_id)

    return templates.TemplateResponse(
        "backtest_detail.html",
        {
            "request": request,
            "summary": summary or {},
            "trades": trades,
            "equity_curve_json": json.dumps(equity_curve),
        },
    )
