"""
/backtest — trigger runs, stream progress via SSE, view results.
"""

import asyncio
import json
import logging
import queue
import re
import threading
from typing import AsyncGenerator

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter()
templates: Jinja2Templates = None

# Per-run progress queues: run_id -> queue.Queue
_progress_queues: dict[str, queue.Queue] = {}

_ALLOWED_EXCHANGES = {"binance", "kraken", "coinbase", "bybit", "okx"}
_ALLOWED_TIMEFRAMES = {"5m", "15m", "1h", "4h", "1d"}
_RUN_ID_RE = re.compile(r"^[0-9a-f]{8}$")


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
            "timeframes": sorted(_ALLOWED_TIMEFRAMES),
            "exchanges": sorted(_ALLOWED_EXCHANGES),
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
    config = request.app.state.config
    runner = request.app.state.backtest_runner

    # Server-side whitelist validation
    if coin not in config.TRACKED_COINS:
        raise HTTPException(status_code=422, detail=f"Unknown coin: {coin}")
    if exchange not in _ALLOWED_EXCHANGES:
        raise HTTPException(status_code=422, detail=f"Unknown exchange: {exchange}")
    if timeframe not in _ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail=f"Unknown timeframe: {timeframe}")

    q: queue.Queue = queue.Queue()
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

    # Wait briefly to get the run_id from the first progress event
    for _ in range(20):
        if captured_id:
            break
        await asyncio.sleep(0.1)

    run_id = captured_id[0] if captured_id else "unknown"
    return RedirectResponse(url=f"/backtest/results?highlight={run_id}", status_code=303)


@router.get("/backtest/progress/{run_id}")
async def progress_stream(run_id: str, request: Request) -> StreamingResponse:
    """SSE endpoint: streams progress events for a running backtest."""
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run_id")

    async def event_generator() -> AsyncGenerator[str, None]:
        q = _progress_queues.get(run_id)
        if q is None:
            yield 'data: {"type": "error", "error": "run not found"}\n\n'
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=1)
                )
                if event is None:
                    yield 'data: {"type": "done"}\n\n'
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
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run_id")

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
