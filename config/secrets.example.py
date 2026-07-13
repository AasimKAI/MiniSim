"""
Copy this file to config/secrets.py and fill in your keys.
config/secrets.py is gitignored and must NEVER be committed.
Leave blank in fixture/paper mode.
"""
BINANCE_TESTNET_API_KEY = ""
BINANCE_TESTNET_API_SECRET = ""
BINANCE_LIVE_API_KEY = ""
BINANCE_LIVE_API_SECRET = ""

# Futures (real shorts). Binance futures TESTNET is a separate registration
# from spot testnet: https://testnet.binancefuture.com (email-only signup).
BINANCE_FUTURES_TESTNET_API_KEY = ""
BINANCE_FUTURES_TESTNET_API_SECRET = ""
BINANCE_LIVE_FUTURES_API_KEY = ""
BINANCE_LIVE_FUTURES_API_SECRET = ""

# Hyperliquid perp DEX (used when config.FUTURES_BACKEND = "hyperliquid").
# The same wallet works on mainnet and testnet (app.hyperliquid-testnet.xyz);
# use a dedicated API wallet key, never your main wallet's key.
HYPERLIQUID_WALLET_ADDRESS = ""
HYPERLIQUID_PRIVATE_KEY = ""

TELEGRAM_BOT_TOKEN = ""   # optional, for big-trade approvals
TELEGRAM_CHAT_ID = ""

# Optional data feed keys (system degrades gracefully without them)
CRYPTOPANIC_TOKEN = ""
