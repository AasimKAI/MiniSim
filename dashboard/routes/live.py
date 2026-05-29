"""
/live — current positions, exposure, regime, kill switch, heartbeat.
Reads from state files only; never touches positions or orders.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter()
templates: Jinja2Templates = None  # injected by server.py


def _read_json(path: str) -> dict:
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
    return {}


def _read_jsonl(path: str, limit: int = 20) -> List[dict]:
    rows = []
    try:
        p = Path(path)
        if not p.exists():
            return []
        with open(p) as f:
            lines = f.readlines()
        for line in reversed(lines[-limit:]):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
    return rows


@router.get("/live", response_class=HTMLResponse)
async def live_page(request: Request):
    config = request.app.state.config

    state = _read_json(f"{config.STATE_DIR}/positions.json")
    positions = list(state.get("positions", {}).values())
    exposure = state.get("current_exposure_usd", 0.0)

    kill_switch_active = Path(config.KILL_SWITCH_PATH).exists()
    kill_reason = ""
    if kill_switch_active:
        try:
            kill_reason = Path(config.KILL_SWITCH_PATH).read_text().strip()
        except Exception:
            pass

    recent_decisions = _read_jsonl(f"{config.DATA_DIR}/decision_log.jsonl", limit=10)

    return templates.TemplateResponse(
        "live.html",
        {
            "request": request,
            "positions": positions,
            "exposure": round(exposure, 2),
            "max_exposure": config.MAX_EXPOSURE_USD,
            "kill_switch_active": kill_switch_active,
            "kill_reason": kill_reason,
            "recent_decisions": recent_decisions,
            "tracked_coins": config.TRACKED_COINS,
        },
    )


@router.get("/live/positions", response_class=HTMLResponse)
async def live_positions_partial(request: Request):
    """HTMX partial — refreshed every 10s."""
    config = request.app.state.config
    state = _read_json(f"{config.STATE_DIR}/positions.json")
    positions = list(state.get("positions", {}).values())
    exposure = state.get("current_exposure_usd", 0.0)
    kill_switch_active = Path(config.KILL_SWITCH_PATH).exists()

    return templates.TemplateResponse(
        "partials/positions.html",
        {
            "request": request,
            "positions": positions,
            "exposure": round(exposure, 2),
            "max_exposure": config.MAX_EXPOSURE_USD,
            "kill_switch_active": kill_switch_active,
        },
    )
