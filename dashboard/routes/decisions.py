"""
/decisions — paginated decision log viewer.
"""

import json
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter()
templates: Jinja2Templates = None


def _read_decisions(path: str, page: int = 1, per_page: int = 25):
    rows = []
    try:
        p = Path(path)
        if not p.exists():
            return [], 0
        with open(p) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        total = len(lines)
        # Newest first
        lines = list(reversed(lines))
        start = (page - 1) * per_page
        page_lines = lines[start : start + per_page]
        for line in page_lines:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        return rows, total
    except Exception as e:
        logger.warning(f"Decision log read error: {e}")
        return [], 0


@router.get("/decisions", response_class=HTMLResponse)
async def decisions_page(request: Request, page: int = Query(default=1, ge=1)):
    config = request.app.state.config
    per_page = 25
    decisions, total = _read_decisions(
        f"{config.DATA_DIR}/decision_log.jsonl", page, per_page
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        "decisions.html",
        {
            "request": request,
            "decisions": decisions,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )
