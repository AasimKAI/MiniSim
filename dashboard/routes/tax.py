"""
/tax — tax ledger summary viewer (HMRC format).
"""

import json
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter()
templates: Jinja2Templates = None


def _read_tax(path: str) -> List[dict]:
    rows = []
    try:
        p = Path(path)
        if not p.exists():
            return []
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception as e:
        logger.warning(f"Tax ledger read error: {e}")
    return rows


@router.get("/tax", response_class=HTMLResponse)
async def tax_page(request: Request):
    config = request.app.state.config
    trades = _read_tax(f"{config.DATA_DIR}/tax_ledger.jsonl")

    # Aggregate by coin
    by_coin: dict = {}
    total_gbp = 0.0
    for t in trades:
        coin = t.get("coin", "?")
        gbp = float(t.get("total_gbp", 0) or 0)
        by_coin.setdefault(coin, {"coin": coin, "trades": 0, "total_gbp": 0.0})
        by_coin[coin]["trades"] += 1
        by_coin[coin]["total_gbp"] += gbp
        total_gbp += gbp

    summary = sorted(by_coin.values(), key=lambda x: x["coin"])
    for s in summary:
        s["total_gbp"] = round(s["total_gbp"], 2)

    return templates.TemplateResponse(
        "tax.html",
        {
            "request": request,
            "trades": list(reversed(trades[-50:])),  # last 50, newest first
            "summary": summary,
            "total_gbp": round(total_gbp, 2),
            "total_trades": len(trades),
            "currency": getattr(config, "TAX_LEDGER_CURRENCY", "GBP"),
        },
    )
