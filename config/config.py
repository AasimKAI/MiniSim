"""
MiniSim v5 — central configuration.

Everything you might want to change lives here. Plain-English comments on
each line so a non-developer can adjust safely.
"""
import os

# ----------------------------------------------------------------------------
# RUN MODE  — start here, this is the most important setting.
#   fixture            -> uses bundled fake data, no internet, no money. Safest.
#   paper              -> simulated trading against live-style data, no money.
#   testnet            -> Binance *test* network. Fake money, real API.
#   live               -> REAL money. Do NOT use until you have run for weeks.
# ----------------------------------------------------------------------------
MODE = os.environ.get("MINISIM_MODE", "paper")

# Coins the system watches.
TRACKED_COINS = ["BTC", "ETH", "XRP", "ADA", "SOL"]

# How often the full think-cycle runs (seconds). 300 = 5 minutes.
COLLECTOR_INTERVAL = 300
# Fast volume scan loop (seconds).
VOLUME_SCAN_INTERVAL = 45
# How long a fetched market quote is reused before refetching (seconds).
# Prevents hammering the data API on the fast exit loop.
MARKET_CACHE_SEC = 60
# Exit watch loop (seconds) — how often open positions are checked.
EXIT_WATCH_INTERVAL = 10

# ----------------------------------------------------------------------------
# MONEY & RISK  (all values in USD unless noted)
# ----------------------------------------------------------------------------
POSITION_SIZE_USD = 100          # size of a single trade
MAX_EXPOSURE_USD = 500           # total across all open trades
BIG_TRADE_THRESHOLD_USD = 1000   # above this, a human must approve

STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_TARGET_1_PERCENT = 5.0    # sell 33% here
TAKE_PROFIT_TARGET_2_PERCENT = 10.0   # sell 33% here
TAKE_PROFIT_TARGET_3_PERCENT = 15.0   # sell 34% here
TRAILING_STOP_PERCENT = 3.0
MAX_HOLD_TIME_HOURS = 48

ROUTINE_SIGNAL_CONFIDENCE_MIN = 0.60
STRONG_SIGNAL_CONFIDENCE_MIN = 0.75

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
LLM_TIMEOUT_SEC = 45
LLM_RETRIES = 2
# If the model is missing or too slow, the system falls back to a deterministic
# rule-based "abstain/neutral" response instead of crashing.

# ----------------------------------------------------------------------------
# MCP SERVERS  (v5 — replaces direct REST API calls)
#   The system talks to small local servers over stdio. Each wraps one concern.
# ----------------------------------------------------------------------------
MCP_SERVERS = {
    "market_data": {
        "command": "python",
        "args": ["-m", "mcp_servers.market_data_server"],
        "enabled": True,
    },
    "news_sentiment": {
        "command": "python",
        "args": ["-m", "mcp_servers.news_sentiment_server"],
        "enabled": True,
    },
    "exchange": {
        "command": "python",
        "args": ["-m", "mcp_servers.exchange_server"],
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

VERSION = "5.0.0"
