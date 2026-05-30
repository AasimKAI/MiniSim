"""
Backtest orchestrator.
Wires OHLCFetcher → SignalReplayer → PaperExchangeClient → metrics.
Writes per-run results (JSONL + summary.json) and updates the SQLite index.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from backtest.llm_cache import LLMCache
from backtest.metrics import calculate as calc_metrics
from backtest.ohlc_fetcher import OHLCFetcher
from backtest.signal_replayer import SignalReplayer

logger = logging.getLogger(__name__)


class _NeutralAnalyst:
    """Stub analyst returning neutral verdicts when an analyst is disabled by config."""

    def __init__(self, name: str):
        self._name = name

    def analyze(self, *args, **kwargs) -> Dict:
        return {
            "analyst": self._name,
            "view": "neutral",
            "confidence": 0.0,
            "status": "disabled",
            "reasoning": "analyst disabled in BACKTEST_ANALYSTS_ENABLED",
        }


class BacktestRunner:
    """Runs a single backtest and records results."""

    def __init__(self, config):
        self.config = config
        self.results_dir = Path(getattr(config, "BACKTEST_RESULTS_DIR", "data/backtest_results"))
        self.ohlc_cache_dir = getattr(config, "OHLC_CACHE_DIR", "data/ohlc_cache")
        self.index_db = self.results_dir / "index.db"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._init_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        coin: str,
        exchange: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        progress_cb: Optional[Callable[[Dict], None]] = None,
    ) -> str:
        """
        Execute a full backtest. Returns run_id.
        Optional progress_cb(event) is called after each bar for live streaming.
        """
        run_id = str(uuid.uuid4())[:8]
        run_dir = self.results_dir / run_id
        run_dir.mkdir(parents=True)

        logger.info(f"[{run_id}] Backtest starting: {coin} {exchange} {timeframe} {start_date}→{end_date}")
        self._upsert_index(run_id, coin, exchange, timeframe, start_date, end_date, "running")

        try:
            symbol = f"{coin}/USDT"
            warmup = getattr(self.config, "BACKTEST_WARMUP_BARS", 50)
            llm_cache_enabled = getattr(self.config, "BACKTEST_LLM_CACHE_ENABLED", True)

            # --- Fetch OHLCV ---
            fetcher = OHLCFetcher(self.ohlc_cache_dir, exchange)
            bars = fetcher.fetch(symbol, timeframe, start_date, end_date, warmup_bars=warmup)
            total_bars = len(bars) - warmup
            if total_bars <= 0:
                raise ValueError("No bars available after warm-up period")

            if progress_cb:
                progress_cb({"type": "start", "run_id": run_id, "total_bars": total_bars})

            # --- Instantiate components ---
            llm_cache = None
            if llm_cache_enabled:
                llm_cache = LLMCache(str(Path(self.ohlc_cache_dir) / "llm_cache.db"))

            replayer = self._build_replayer(coin, llm_cache, warmup)

            # --- Replay ---
            trades: List[Dict] = []
            open_position: Optional[Dict] = None
            trade_file = run_dir / "trades.jsonl"
            event_file = run_dir / "events.jsonl"
            bars_processed = 0

            from execution.exchange_client import PaperExchangeClient
            from execution.exit_manager import ExitManager
            from execution.risk_manager import RiskManager

            paper = PaperExchangeClient()
            risk_mgr = RiskManager(self.config)
            exit_mgr = ExitManager(self.config)
            exposure = 0.0

            with open(trade_file, "a") as tf, open(event_file, "a") as ef:
                for event in replayer.replay(bars):
                    bars_processed += 1
                    close = event["close"]
                    decision = event["decision"]
                    signal = event.get("signal")

                    # --- Exit check (priority) ---
                    if open_position:
                        open_position = exit_mgr.update_trailing_stop(open_position, close)
                        exit_order = exit_mgr.check_exit_conditions(
                            open_position, close, event["regime"]
                        )
                        if exit_order:
                            trade = self._close_position(open_position, exit_order, close, paper)
                            trades.append(trade)
                            exposure -= open_position.get("position_size_usd", 0)
                            open_position = None
                            tf.write(json.dumps(trade) + "\n")

                    # --- Entry ---
                    if not open_position and signal and decision in ("entry_buy", "entry_sell"):
                        approved, _, size = risk_mgr.check_signal(signal, exposure, False)
                        if approved:
                            open_position = self._open_position(signal, size, close, paper)
                            exposure += size
                            exit_plan = risk_mgr.calculate_exit_plan(close, coin, signal)
                            open_position.update(
                                {
                                    "stop_loss": exit_plan["stop_loss"],
                                    "take_profit_targets": exit_plan["profit_targets"],
                                    "thesis_condition": exit_plan["thesis_condition"],
                                    "max_hold_time_sec": exit_plan["max_hold_time_sec"],
                                    "trailing_stop_activated": False,
                                    "trailing_stop": close,
                                    "closed_exit_triggers": [],
                                }
                            )

                    ef.write(json.dumps({
                        "bar_index": event["bar_index"],
                        "timestamp": event["timestamp"],
                        "close": close,
                        "verdicts": event["verdicts"],
                        "regime": event["regime"],
                        "decision": decision,
                        "llm_called": event["llm_called"],
                    }) + "\n")

                    if progress_cb:
                        pct = bars_processed / total_bars * 100
                        progress_cb({"type": "progress", "run_id": run_id, "pct": round(pct, 1), "bar": bars_processed})

            # Force-close any open position at last bar close
            if open_position and bars:
                last_close = bars[-1][4]
                fake_exit = {"trigger": "end_of_backtest", "quantity_percent": 100, "exit_price": last_close}
                trade = self._close_position(open_position, fake_exit, last_close, paper)
                trades.append(trade)
                with open(trade_file, "a") as tf:
                    tf.write(json.dumps(trade) + "\n")

            # --- Metrics ---
            llm_stats = llm_cache.stats if llm_cache else {"hits": 0, "misses": 0, "hit_rate": 0.0}
            metrics = calc_metrics(trades, start_date=start_date, end_date=end_date)

            # Mark suspect if too many LLM calls failed (results may be unreliable)
            final_status = "completed"
            if replayer.llm_failure_rate > 0.5:
                final_status = "suspect"
                logger.warning(
                    f"[{run_id}] LLM failure rate {replayer.llm_failure_rate:.0%} — "
                    "results marked suspect"
                )

            # events.jsonl served streaming only; discard after metrics are computed
            try:
                event_file.unlink(missing_ok=True)
            except Exception:
                pass

            summary = {
                "run_id": run_id,
                "coin": coin,
                "exchange": exchange,
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "total_bars": bars_processed,
                "llm_calls": replayer.llm_attempt_count,
                "llm_failure_rate": round(replayer.llm_failure_rate, 3),
                "llm_cache_hit_rate": round(llm_stats["hit_rate"], 3),
                "status": final_status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                **{k: v for k, v in metrics.items() if k != "equity_curve"},
            }
            (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            self._upsert_index(run_id, coin, exchange, timeframe, start_date, end_date, final_status, metrics, llm_stats)

            logger.info(
                f"[{run_id}] Backtest complete: "
                f"return={metrics['total_return_pct']:.1f}% "
                f"sharpe={metrics['sharpe_ratio']:.2f} "
                f"trades={metrics['trade_count']}"
            )
            if progress_cb:
                progress_cb({"type": "done", "run_id": run_id, "summary": summary})

        except Exception as e:
            logger.error(f"[{run_id}] Backtest failed: {e}", exc_info=True)
            self._upsert_index(run_id, coin, exchange, timeframe, start_date, end_date, "failed")
            if progress_cb:
                progress_cb({"type": "error", "run_id": run_id, "error": str(e)})

        return run_id

    # ------------------------------------------------------------------
    # Results query (used by dashboard)
    # ------------------------------------------------------------------

    def list_runs(self, limit: int = 50) -> List[Dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM runs LIMIT 0").description or []]
        if not cols:
            cols = self._run_columns()
        return [dict(zip(cols, r)) for r in rows]

    def get_summary(self, run_id: str) -> Optional[Dict]:
        run_dir = self.results_dir / run_id
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            return None
        return json.loads(summary_path.read_text())

    def get_equity_curve(self, run_id: str) -> List[Dict]:
        """Return equity curve from trades.jsonl for Chart.js rendering."""
        trades = self._load_trades(run_id)
        metrics = calc_metrics(trades)
        return metrics.get("equity_curve", [])

    def get_trades(self, run_id: str) -> List[Dict]:
        return self._load_trades(run_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_replayer(self, coin: str, llm_cache, warmup: int) -> SignalReplayer:
        from analysts.technical_analyst import TechnicalAnalyst
        from analysts.volume_analyst import VolumeAnalyst
        from analysts.regime_detector import RegimeDetector
        from decision.regime_filter import RegimeFilter
        from decision.researcher import BullResearcher, BearResearcher
        from decision.ceo_agent import CEOAgent

        enabled = getattr(self.config, "BACKTEST_ANALYSTS_ENABLED", {})
        tech = (
            TechnicalAnalyst(self.config)
            if enabled.get("technical", True)
            else _NeutralAnalyst("technical")
        )
        vol = (
            VolumeAnalyst(self.config)
            if enabled.get("volume", True)
            else _NeutralAnalyst("volume")
        )

        return SignalReplayer(
            coin=coin,
            technical_analyst=tech,
            volume_analyst=vol,
            regime_detector=RegimeDetector(self.config),
            regime_filter=RegimeFilter(self.config),
            bull_researcher=BullResearcher(self.config),
            bear_researcher=BearResearcher(self.config),
            ceo_agent=CEOAgent(self.config),
            config=self.config,
            llm_cache=llm_cache,
            warmup_bars=warmup,
        )

    def _open_position(self, signal: Dict, size: float, price: float, paper) -> Dict:
        coin = signal["coin"]
        side = "LONG" if signal["decision"] == "entry_buy" else "SHORT"
        qty = size / price if price > 0 else 0
        coid = f"bt_{signal.get('signal_id', str(uuid.uuid4()))[:8]}_entry"
        paper.execute(f"{coin}/USDT", side, qty, price, coid)
        return {
            "position_id": f"pos_{coid}",
            "signal_id": signal.get("signal_id", ""),
            "coin": coin,
            "side": side,
            "entry_price": price,
            "entry_quantity": qty,
            "remaining_quantity": qty,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "position_size_usd": size,
            "remaining_exposure_usd": size,
            "status": "open",
        }

    def _close_position(self, position: Dict, exit_order: Dict, price: float, paper) -> Dict:
        coin = position["coin"]
        qty = position.get("remaining_quantity", 0)
        side = position["side"]

        # Apply slippage: selling (LONG exit) gets a lower price; buying back (SHORT exit) costs more
        slip = getattr(self.config, "SLIPPAGE_PERCENT", 0.05) / 100
        exit_price = price * (1 - slip) if side == "LONG" else price * (1 + slip)

        coid = f"bt_{position['position_id'][:8]}_exit"
        paper.execute(f"{coin}/USDT", "SELL", qty, exit_price, coid)

        entry = position["entry_price"]
        raw_pnl = (exit_price - entry) * qty if side == "LONG" else (entry - exit_price) * qty
        fee_pct = getattr(self.config, "TAKER_FEE_PERCENT", 0.1) / 100
        fees = (entry * qty + exit_price * qty) * fee_pct
        pnl = raw_pnl - fees
        pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0

        return {
            "status": "closed",
            "coin": coin,
            "side": side,
            "entry_price": entry,
            "exit_price": round(exit_price, 6),
            "quantity": qty,
            "pnl_usd": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
            "trigger": exit_order.get("trigger", "unknown"),
            "entry_ts": position["entry_timestamp"],
            "exit_ts": datetime.now(timezone.utc).isoformat(),
            "signal_id": position.get("signal_id", ""),
        }

    def _load_trades(self, run_id: str) -> List[Dict]:
        path = self.results_dir / run_id / "trades.jsonl"
        if not path.exists():
            return []
        trades = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(json.loads(line))
        return trades

    # ------------------------------------------------------------------
    # SQLite index
    # ------------------------------------------------------------------

    def _init_index(self):
        with self._db() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS runs (
                    {', '.join(f'{c} {t}' for c, t in self._run_schema())}
                )
                """
            )

    def _upsert_index(
        self,
        run_id, coin, exchange, timeframe, start_date, end_date, status,
        metrics=None, llm_stats=None,
    ):
        m = metrics or {}
        ls = llm_stats or {}
        with self._db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                  (run_id, coin, exchange, timeframe, start_date, end_date,
                   total_return_pct, sharpe_ratio, max_drawdown_pct,
                   win_rate, trade_count, llm_cache_hit_rate, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id, coin, exchange, timeframe, start_date, end_date,
                    m.get("total_return_pct"),
                    m.get("sharpe_ratio"),
                    m.get("max_drawdown_pct"),
                    m.get("win_rate"),
                    m.get("trade_count"),
                    ls.get("hit_rate"),
                    status,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.index_db), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _run_schema():
        return [
            ("run_id", "TEXT PRIMARY KEY"),
            ("coin", "TEXT"),
            ("exchange", "TEXT"),
            ("timeframe", "TEXT"),
            ("start_date", "TEXT"),
            ("end_date", "TEXT"),
            ("total_return_pct", "REAL"),
            ("sharpe_ratio", "REAL"),
            ("max_drawdown_pct", "REAL"),
            ("win_rate", "REAL"),
            ("trade_count", "INTEGER"),
            ("llm_cache_hit_rate", "REAL"),
            ("status", "TEXT"),
            ("created_at", "TEXT"),
        ]

    @staticmethod
    def _run_columns():
        return [c for c, _ in BacktestRunner._run_schema()]
