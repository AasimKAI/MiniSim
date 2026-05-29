"""
Secrets configuration example.
COPY TO secrets.py and fill in with real values.
NEVER commit secrets.py to git.
"""

# BINANCE TESTNET - obtain from https://testnet.binance.vision
BINANCE_TESTNET_API_KEY = "your-testnet-api-key-here"
BINANCE_TESTNET_API_SECRET = "your-testnet-api-secret-here"

# BINANCE LIVE (future use only) - TRADE-ONLY KEYS MANDATORY
# BINANCE_LIVE_API_KEY = "your-live-trade-only-api-key-here"
# BINANCE_LIVE_API_SECRET = "your-live-trade-only-api-secret-here"

# EXTERNAL API KEYS (feed sources)
COINGECKO_API_KEY = None  # CoinGecko free tier (no key needed)
COIN_RANKINGS_API_KEY = None  # optional
NEWSAPI_KEY = None  # https://newsapi.org (free tier limited)
ALPHA_VANTAGE_KEY = None  # for econ calendar (if used)

# REDDIT API (for sentiment)
REDDIT_CLIENT_ID = None
REDDIT_CLIENT_SECRET = None
REDDIT_USER_AGENT = None

# TWITTER/X API (for sentiment)
TWITTER_BEARER_TOKEN = None

# OLLAMA LOCAL LLM
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama2"

# TELEGRAM BOT (for approvals & notifications)
TELEGRAM_BOT_TOKEN = None
TELEGRAM_CHAT_ID = None  # your chat ID (must match for approval security)

# FX RATE SOURCE (for tax ledger GBP conversion)
# Options: "coinbase", "binance", "coingecko"
FX_RATE_SOURCE = "coingecko"
FX_API_KEY = None  # if needed by chosen source

# SLACK (optional notifications)
SLACK_WEBHOOK_URL = None

# DATABASE (if using PostgreSQL for historical storage)
# DB_HOST = "localhost"
# DB_PORT = 5432
# DB_NAME = "crypto_signals"
# DB_USER = "crypto_user"
# DB_PASSWORD = "secure_password"

# RASPBERRY PI DEPLOYMENT
# When moving to Pi, ensure config.py paths and secrets.py are present
# Testnet mode requires Binance Testnet keys; paper mode does not.
RPI_DEPLOYMENT = False
