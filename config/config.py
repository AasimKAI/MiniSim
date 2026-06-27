"""
MiniSim v6 — central configuration.

Everything you might want to change lives here. Plain-English comments on
each line so a non-developer can adjust safely.
"""
import os, sys

# ----------------------------------------------------------------------------
# RUN MODE  — start here, this is the most important setting.
#   fixture            -> uses bundled fake data, no internet, no money. Safest.
#   paper              -> simulated trading against live-style data, no money.
#   testnet            -> Binance *test* network. Fake money, real API.
#   live               -> REAL money. Do NOT use until you have run for weeks.
# ----------------------------------------------------------------------------
MODE = os.environ.get("MINISIM_MODE", "paper")

# Coins the system watches.
TRACKED_COINS = ["BTC", "ETH", "XRP", "ADA", "SOL",
                 "BNB", "DOGE", "AVAX", "DOT", "LINK",
                 "LTC", "NEAR", "UNI", "ARB", "ATOM"]

# How often the full think-cycle runs (seconds).
# One 15-coin cycle takes ~6-7 minutes; 900s pause → ~22 min effective period.
COLLECTOR_INTERVAL = 900
# Fast volume scan loop (seconds). (Defined for completeness; not currently wired.)
VOLUME_SCAN_INTERVAL = 45
# How long a fetched market quote is reused before refetching (seconds).
# 600s covers the full cycle so all 15 coins see the same data vintage.
MARKET_CACHE_SEC = 600
# Exit watch loop (seconds) — how often open positions are checked for stop-loss/TP.
EXIT_WATCH_INTERVAL = 30
# Candle timeframe passed to the Binance klines API.
# 15m gives cleaner signals and matches the ~22 min analysis cadence.
CANDLE_INTERVAL = "15m"

# ----------------------------------------------------------------------------
# MONEY & RISK  (all values in USD unless noted)
# ----------------------------------------------------------------------------
POSITION_SIZE_USD = 100          # size of a single trade
MAX_EXPOSURE_USD = 500           # total across all open trades
BIG_TRADE_THRESHOLD_USD = 1000   # above this, a human must approve

# --------------------------------------------------------------------------
# SMALL ACCOUNT MODE  — if your starting capital is under ~$5,000, uncomment
#   the three lines below and set ACCOUNT_SIZE_USD to your actual balance.
#   Position size = 2% of capital (minimum $20); max exposure = 15%.
#
#   Example for $1,000:
#     ACCOUNT_SIZE_USD  = 1000   → POSITION_SIZE_USD = $20, MAX_EXPOSURE_USD = $150
#   Example for $2,500:
#     ACCOUNT_SIZE_USD  = 2500   → POSITION_SIZE_USD = $50, MAX_EXPOSURE_USD = $375
#
# ACCOUNT_SIZE_USD  = 1000
# POSITION_SIZE_USD = max(20, round(ACCOUNT_SIZE_USD * 0.02 / 5) * 5)
# MAX_EXPOSURE_USD  = max(100, round(ACCOUNT_SIZE_USD * 0.15 / 10) * 10)
# --------------------------------------------------------------------------

STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_TARGET_1_PERCENT = 5.0    # sell 33% here
TAKE_PROFIT_TARGET_2_PERCENT = 10.0   # sell 33% here
TAKE_PROFIT_TARGET_3_PERCENT = 15.0   # sell 34% here
TRAILING_STOP_PERCENT = 3.0
MAX_HOLD_TIME_HOURS = 48
MIN_ORDER_NOTIONAL_USD = 6.0          # Binance spot min is $5; 6 gives a small buffer

# Futures shorts (USDM perpetual, testnet.binancefuture.com)
FUTURES_LEVERAGE    = 1            # 1x = no leverage; increase only deliberately
FUTURES_MARGIN_TYPE = "ISOLATED"   # ISOLATED is safer than CROSS for automated trading

ROUTINE_SIGNAL_CONFIDENCE_MIN = 0.68   # raised from 0.65 — filters borderline entries
STRONG_SIGNAL_CONFIDENCE_MIN = 0.80

# ----------------------------------------------------------------------------
# REGIME FILTER
# ----------------------------------------------------------------------------
REGIME_FILTER_ENABLED = True
REGIME_FILTER_STRICT = False     # True = only trade in clearly trending markets

# ----------------------------------------------------------------------------
# QUANTIZED LOCAL LLM  (v5 — replaces Ollama)
#   The model file is a GGUF quantized model that runs on-device via
#   llama-cpp-python. Defaults are tuned for a Raspberry Pi 5 (16GB) + NVMe.
# ----------------------------------------------------------------------------
LLM_BACKEND = os.environ.get("MINISIM_LLM_BACKEND", "llamacpp")  # llamacpp | ollama | stub
LLM_MODEL_PATH = os.environ.get(
    "MINISIM_LLM_MODEL",
    os.path.join(os.path.dirname(__file__), "..", "models",
                 "qwen2.5-3b-instruct-q4_k_m.gguf"),
)
LLM_CONTEXT_TOKENS = 4096
LLM_MAX_OUTPUT_TOKENS = 384
LLM_THREADS = int(os.environ.get("MINISIM_LLM_THREADS", "4"))   # Pi 5 has 4 cores
LLM_TEMPERATURE = 0.2            # low = consistent, less random
LLM_TIMEOUT_SEC = 120   # first call includes model load (~45s on Pi 5); 120s gives headroom
LLM_RETRIES = 2
# If the model is missing or too slow, the system falls back to a deterministic
# rule-based "abstain/neutral" response instead of crashing.

# ----------------------------------------------------------------------------
# MCP SERVERS  (v5 — replaces direct REST API calls)
#   The system talks to small local servers over stdio. Each wraps one concern.
# ----------------------------------------------------------------------------
MCP_SERVERS = {
    "market_data": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.market_data_server"],
        "enabled": True,
    },
    "news_sentiment": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.news_sentiment_server"],
        "enabled": True,
    },
    "exchange": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.exchange_server"],
        "enabled": True,
    },
    "macro": {
        "command": sys.executable,
        "args": ["-m", "mcp_servers.macro_server"],
        "enabled": True,
    },
}

# ----------------------------------------------------------------------------
# DASHBOARDS  (v5 — two tailored views)
# ----------------------------------------------------------------------------
DASHBOARD_HOST = "0.0.0.0"       # 0.0.0.0 = reachable from your phone on the LAN
DASHBOARD_PORT = 8770
DASHBOARD_TOKEN = os.environ.get("MINISIM_DASH_TOKEN", "")  # optional shared secret

# ----------------------------------------------------------------------------
# PATHS
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATE_DIR = os.path.join(BASE_DIR, "state")
KILL_SWITCH_FILE = os.path.join(STATE_DIR, "kill_switch.lock")

DECISION_LOG = os.path.join(DATA_DIR, "decision_log.jsonl")
TAX_LEDGER = os.path.join(DATA_DIR, "tax_ledger.jsonl")
POSITIONS_FILE = os.path.join(STATE_DIR, "positions.json")
STATUS_FILE = os.path.join(STATE_DIR, "status.json")   # dashboards read this
EQUITY_HISTORY_FILE = os.path.join(STATE_DIR, "equity_history.json")  # for the equity chart

VERSION = "6.0.0"
