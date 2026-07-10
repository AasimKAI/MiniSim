"""
v5 MCP client — the ONLY way the trading system reaches data and the exchange.

Design goals:
 * Genuinely speak MCP: launch the configured servers and call their tools.
 * Never take the system down: if the MCP transport is unavailable (package
   missing, server crash, Pi under load) it transparently falls back to calling
   the same server logic in-process. The rest of the codebase is unaffected.

Usage (synchronous, simple for the orchestrator):
    from mcp_client.client import get_client
    mc = get_client()
    candles = mc.candles("BTC")
    fill = mc.place_order("BTC", "BUY", 0.01, "order-123")
"""
import os, asyncio, json, threading, atexit
from config import config
from common import get_logger

log = get_logger("mcp-client")

# In-process fallback map: (server, tool) -> python callable
from mcp_servers import _marketdata_core as _md
from mcp_servers import _news_core as _news
from mcp_servers import _exchange_core as _ex
from mcp_servers import _macro_core as _macro

_FALLBACK = {
    ("market_data", "get_candles"): lambda a: _md.get_candles(a["coin"], a.get("count", 200)),
    ("market_data", "get_ticker"): lambda a: _md.get_ticker(a["coin"]),
    ("market_data", "get_orderbook"): lambda a: _md.get_orderbook(a["coin"]),
    ("news_sentiment", "get_headlines"): lambda a: _news.get_headlines(a["coin"], a.get("limit", 5)),
    ("exchange", "balance"): lambda a: _ex.balance(),
    ("exchange", "positions"): lambda a: _ex.positions(),
    ("exchange", "place_order"): lambda a: _ex.place_order(
        a["coin"], a["side"], a["quantity"], a.get("client_order_id") or None),
    ("exchange", "update_meta"): lambda a: _ex.update_meta(
        a["coin"], a.get("peak_pnl"), a.get("add_target"), a.get("extra")),
    ("market_data", "get_taker_ratio"): lambda a: _md.get_taker_ratio(a["coin"]),
    ("macro", "get_fear_greed"):      lambda a: _macro.get_fear_greed(),
    ("macro", "get_funding_rates"):   lambda a: _macro.get_funding_rates(),
    ("macro", "get_dominance"):       lambda a: _macro.get_dominance(),
    ("macro", "get_open_interest"):   lambda a: _macro.get_open_interest(),
    ("macro", "get_long_short_ratio"): lambda a: _macro.get_long_short_ratio(),
    ("macro", "get_tradfi"):          lambda a: _macro.get_tradfi(),
}

# Tools that must NEVER be auto-retried/fallback-executed on transport error,
# because a timeout may mean the order already filled (avoids double execution).
_NON_RETRYABLE = {("exchange", "place_order")}

# Tools whose return is a LIST — so a one-element result isn't collapsed to a dict.
_LIST_TOOLS = {("market_data", "get_candles"), ("news_sentiment", "get_headlines"), ("exchange", "positions")}


class _LoopThread:
    """Runs a dedicated asyncio loop in a background thread for MCP sessions."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro, timeout=60):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


class MCPClient:
    def __init__(self):
        self.transport_ok = False
        self._sessions = {}
        self._stack = None
        self._loop = None
        try:
            self._connect()
        except Exception as e:  # noqa
            log.warning("MCP transport unavailable (%s) — using in-process fallback", e)

    # ---------- transport setup ----------
    def _connect(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client, get_default_environment
        from contextlib import AsyncExitStack

        # CRITICAL: the SDK strips the environment for subprocesses. We MUST
        # forward the run mode (and LLM settings) or the exchange server would
        # silently default to the PAPER simulator even in testnet/live.
        child_env = get_default_environment()
        child_env.update({k: v for k, v in os.environ.items() if k.startswith("MINISIM_")})
        child_env["MINISIM_MODE"] = config.MODE
        child_env["MINISIM_LLM_BACKEND"] = config.LLM_BACKEND
        child_env["MINISIM_LLM_MODEL"] = os.path.abspath(config.LLM_MODEL_PATH)

        self._loop = _LoopThread()

        async def _open():
            stack = AsyncExitStack()
            for name, cfg in config.MCP_SERVERS.items():
                if not cfg.get("enabled", True):
                    continue
                params = StdioServerParameters(command=cfg["command"], args=cfg["args"],
                                               env=child_env)
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._sessions[name] = session
            return stack

        self._stack = self._loop.run(_open(), timeout=90)
        self.transport_ok = True
        atexit.register(self.close)
        log.info("MCP transport connected: %s", list(self._sessions))

    def close(self):
        if self._stack and self._loop:
            try:
                self._loop.run(self._stack.aclose(), timeout=10)
            except Exception:  # noqa
                pass

    # ---------- core call ----------
    def call(self, server, tool, **args):
        if self.transport_ok and server in self._sessions:
            try:
                return self._call_transport(server, tool, args)
            except Exception as e:  # noqa
                if (server, tool) in _NON_RETRYABLE:
                    # Do NOT re-execute — the order may have already filled.
                    log.error("MCP %s.%s errored (%s); NOT retried to avoid double execution",
                              server, tool, e)
                    return {"status": "unknown", "reason": f"transport error: {e}",
                            "client_order_id": args.get("client_order_id")}
                log.warning("MCP call %s.%s failed (%s) — falling back", server, tool, e)
        fn = _FALLBACK[(server, tool)]
        return fn(args)

    def _call_transport(self, server, tool, args):
        session = self._sessions[server]
        is_list = (server, tool) in _LIST_TOOLS

        async def _do():
            res = await session.call_tool(tool, arguments=args)
            sc = getattr(res, "structuredContent", None)
            if isinstance(sc, dict) and "result" in sc:
                return sc["result"]
            if isinstance(sc, dict) and not is_list:
                return sc
            # Parse text content blocks (FastMCP emits one block per list item).
            blocks = []
            for c in (res.content or []):
                txt = getattr(c, "text", None)
                if txt is None:
                    continue
                try:
                    blocks.append(json.loads(txt))
                except Exception:  # noqa
                    blocks.append(txt)
            if is_list:
                return blocks                       # always a list (even length 0/1)
            if not blocks:
                return None
            return blocks[0] if len(blocks) == 1 else blocks

        return self._loop.run(_do(), timeout=config.LLM_TIMEOUT_SEC + 30)

    # ---------- friendly named helpers ----------
    def candles(self, coin, count=200):
        return self.call("market_data", "get_candles", coin=coin, count=count) or []

    def ticker(self, coin):
        return self.call("market_data", "get_ticker", coin=coin)

    def orderbook(self, coin):
        return self.call("market_data", "get_orderbook", coin=coin)

    def taker_ratio(self, coin) -> float:
        r = self.call("market_data", "get_taker_ratio", coin=coin)
        return float(r) if r is not None else 0.5

    def headlines(self, coin, limit=5):
        return self.call("news_sentiment", "get_headlines", coin=coin, limit=limit) or []

    def balance(self):
        return self.call("exchange", "balance")

    def positions(self):
        return self.call("exchange", "positions") or []

    def place_order(self, coin, side, quantity, client_order_id=None):
        return self.call("exchange", "place_order", coin=coin, side=side,
                         quantity=quantity, client_order_id=client_order_id or "")

    def update_meta(self, coin, peak_pnl=None, add_target=None, extra=None):
        """extra: optional dict of per-position overrides (e.g. strat_sl,
        strat_tp1…) persisted in position meta and merged into positions()."""
        return self.call("exchange", "update_meta", coin=coin,
                         peak_pnl=peak_pnl, add_target=add_target, extra=extra)

    def fear_greed(self):
        return self.call("macro", "get_fear_greed") or {}

    def funding_rates(self):
        return self.call("macro", "get_funding_rates") or {}

    def dominance(self):
        return self.call("macro", "get_dominance") or {}

    def open_interest(self):
        return self.call("macro", "get_open_interest") or {}

    def long_short_ratio(self):
        return self.call("macro", "get_long_short_ratio") or {}

    def tradfi(self):
        return self.call("macro", "get_tradfi") or {}

    def status(self):
        return {"transport": "mcp" if self.transport_ok else "in-process",
                "servers": list(self._sessions) or list({k[0] for k in _FALLBACK})}


_CLIENT = None
def get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = MCPClient()
    return _CLIENT
