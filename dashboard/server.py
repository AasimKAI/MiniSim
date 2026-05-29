"""
FastAPI dashboard server.
Launched in a background thread from main.py.
"""

import logging
import threading

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.auth import DashboardAuth
from dashboard.routes import backtest as bt_routes
from dashboard.routes import decisions as dec_routes
from dashboard.routes import live as live_routes
from dashboard.routes import tax as tax_routes

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = "dashboard/templates"
_STATIC_DIR = "dashboard/static"


def create_app(config, backtest_runner) -> FastAPI:
    app = FastAPI(title="MiniSim Dashboard", docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.backtest_runner = backtest_runner
    auth = DashboardAuth(config)
    app.state.auth = auth

    # Static files
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # Templates — injected into each route module
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)
    live_routes.templates = templates
    dec_routes.templates = templates
    tax_routes.templates = templates
    bt_routes.templates = templates

    # ------------------------------------------------------------------
    # Auth middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        # Pass-through: static assets and login endpoints
        if path.startswith("/static") or path.startswith("/login"):
            return await call_next(request)
        redirect = auth.require_auth(request)
        if redirect:
            return redirect
        return await call_next(request)

    # ------------------------------------------------------------------
    # Login routes
    # ------------------------------------------------------------------
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse("login.html", {"request": request})

    @app.post("/login/request")
    async def login_request(request: Request):
        result = auth.request_access()
        return templates.TemplateResponse(
            "login.html", {"request": request, "message": result["message"], "ok": result["ok"]}
        )

    @app.get("/login/verify")
    async def login_verify(token: str, request: Request):
        session_id = auth.verify_token(token)
        if not session_id:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "message": "Invalid or expired link. Please request a new one.", "ok": False},
            )
        response = RedirectResponse(url="/live")
        auth.set_session_cookie(response, session_id)
        return response

    # ------------------------------------------------------------------
    # Feature routes
    # ------------------------------------------------------------------
    app.include_router(live_routes.router)
    app.include_router(dec_routes.router)
    app.include_router(tax_routes.router)
    app.include_router(bt_routes.router)

    @app.get("/")
    async def root():
        return RedirectResponse(url="/live")

    return app


def start_dashboard(config, backtest_runner):
    """Launch uvicorn in a daemon thread. Called from main.py."""
    host = getattr(config, "DASHBOARD_HOST", "0.0.0.0")
    port = getattr(config, "DASHBOARD_PORT", 8080)

    app = create_app(config, backtest_runner)

    def _run():
        uvicorn.run(app, host=host, port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True, name="dashboard")
    t.start()
    logger.info(f"Dashboard started on http://{host}:{port}")
    return t
