# Accounts & API Keys — what you need, and where the login details go

Plain-English guide to every account MiniSim can use, which modes need them,
and exactly where to save the keys. **Start here before touching `testnet` or
`live` mode.**

---

## The short version

| Mode / feature | Accounts needed | Secrets fields to fill |
|---|---|---|
| `fixture` (offline demo) | **None** | — |
| `paper` (default — pretend money, real prices) | **None** | — |
| `testnet` longs (fake money, real exchange) | Binance **Spot testnet** | `BINANCE_TESTNET_API_KEY` / `_SECRET` |
| `testnet` real shorts | Binance **Futures testnet** (separate signup) | `BINANCE_FUTURES_TESTNET_API_KEY` / `_SECRET` |
| Shorts via Hyperliquid (`FUTURES_BACKEND="hyperliquid"`) | A crypto wallet + HL API wallet | `HYPERLIQUID_WALLET_ADDRESS` / `_PRIVATE_KEY` |
| `live` (real money — read the warnings) | Binance account with API keys | `BINANCE_LIVE_API_KEY` / `_SECRET` (+ futures fields if eligible) |

Things you do **not** need an account for: market prices (Binance public API /
CoinGecko), news headlines (free RSS), Fear & Greed, funding rates, VIX/DXY
(yfinance) — all keyless. **The AI model runs locally on the Pi**, so there is
no OpenAI/Anthropic/cloud account and no monthly API bill.

---

## Where login details are saved

All keys live in **one file**: `config/secrets.py`. Create it by copying the
template, then edit it:

```bash
cp config/secrets.example.py config/secrets.py
nano config/secrets.py          # paste keys between the quotes
chmod 600 config/secrets.py     # only your user can read it
```

Rules that keep you safe:

- `config/secrets.py` is **gitignored** — it must never be committed, emailed,
  pasted into chat tools, or backed up to shared folders. Check with
  `git status`: it should never appear.
- Never put keys in `config/config.py` — that file IS committed.
- Fill in **only** the fields for the mode you're using; leave the rest as
  empty strings. In fixture/paper mode the file can stay empty (or not exist).
- The only non-account secret is the optional dashboard token, which is an
  environment variable, not a file entry: `export MINISIM_DASH_TOKEN=...`
  before starting the dashboard, if you want password-protected pages.

On startup MiniSim's preflight check refuses to run in testnet/live if it
cannot read a real balance with your keys — a wrong key fails loudly at boot,
not silently at trade time.

---

## Account 1 — Binance Spot testnet (fake money, real order flow)

Used for: `MODE = "testnet"` longs (BUY/SELL).

1. Go to **https://testnet.binance.vision** and log in (it uses a GitHub
   account — create one first if needed; it's free).
2. Click **Generate HMAC-SHA-256 Key**. Copy both values immediately (the
   secret is shown once).
3. Paste into `config/secrets.py` as `BINANCE_TESTNET_API_KEY` and
   `BINANCE_TESTNET_API_SECRET`.

Testnet balances are fake and reset periodically — that's normal.

## Account 2 — Binance Futures testnet (fake money, real shorts)

Used for: real SHORT/COVER orders in testnet mode. **This is a separate
website, separate account, and separate keys from the spot testnet.**

1. Go to **https://testnet.binancefuture.com** and register (email signup;
   historically no KYC — UK users should simply try it, since testnet trading
   is fake funds and not a regulated derivatives sale).
2. Find **API Key** on the page (bottom panel) and copy the key + secret.
3. Paste into `BINANCE_FUTURES_TESTNET_API_KEY` / `_SECRET`.

Without these, testnet shorts fall back to the built-in paper simulation
(clearly hybrid — see FIXES.md).

## Account 3 — Hyperliquid (perp DEX alternative for shorts)

Used for: `FUTURES_BACKEND = "hyperliquid"` in `config/config.py` (or
`export MINISIM_FUTURES_BACKEND=hyperliquid`). Useful if you cannot obtain
Binance futures keys (e.g. UK retail).

1. You need an EVM wallet address. On **https://app.hyperliquid-testnet.xyz**
   connect a wallet, use the faucet for test USDC.
2. Create a **dedicated API wallet** (Hyperliquid's "API" page generates an
   agent wallet for trading). **Never put your main wallet's private key in
   any config file.**
3. Paste into `HYPERLIQUID_WALLET_ADDRESS` and `HYPERLIQUID_PRIVATE_KEY`.

⚠ This adapter is flag-gated and **unverified against the venue** — run it on
the Hyperliquid *testnet* first and watch `data/reconciliation.jsonl`.
Mainnet perp venues generally restrict UK retail users — check the venue's
terms yourself before any real-money use.

## Account 4 — Binance live (real money)

Only after weeks of testnet behaviour you trust. Create API keys at
binance.com → API Management, then fill `BINANCE_LIVE_API_KEY` / `_SECRET`
(and the `BINANCE_LIVE_FUTURES_*` fields only if your account has futures —
not available to UK retail).

**Key-permission checklist (do all of these):**

- ✅ Enable **spot trading** permission only.
- ❌ **Disable withdrawals** on the key — MiniSim never needs them, and a
  leaked key then can't drain funds off-exchange.
- ✅ **Restrict the key to your Pi's IP address** (router/static IP or VPN IP).
- ✅ Use a fresh key for MiniSim — don't reuse keys from other tools.
- 🔁 If a key may have leaked, delete it on Binance immediately and reissue.

## Listed but optional / not required today

- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — reserved for big-trade approval
  alerts; the current build does not send Telegram messages yet, so you can
  leave these blank.
- `CRYPTOPANIC_TOKEN` — reserved; the current build reads free RSS feeds and
  needs no news key.
- `MINISIM_DASH_TOKEN` (env var) — optional shared secret that makes the
  dashboards ask for a token; recommended if your Wi-Fi has users you don't
  fully trust.
