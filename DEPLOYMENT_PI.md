# Crypto Signal System v4 - Raspberry Pi Deployment Guide

Complete step-by-step instructions for deploying the Crypto Signal System v4 to a Raspberry Pi 5.

## Prerequisites

### Hardware
- **Raspberry Pi 5** (4GB+ RAM recommended, 8GB+ preferred)
- **MicroSD Card** (32GB+ recommended)
- **Power Supply** (5.1V/5A USB-C)
- **Ethernet** or WiFi connection
- **Optional:** Case with cooling

### Software Requirements
- Raspberry Pi OS Bookworm (64-bit)
- Python 3.9+ (included in latest Pi OS)
- pip package manager
- Git (optional, for version control)

### External Services (Free/Testnet)
- **Binance Testnet Account** - https://testnet.binance.vision (FREE)
- **Ollama** - Local LLM (runs on Pi)
- **Telegram Bot** (optional) - For approvals
- **API Keys** (free tiers available):
  - CoinGecko API (free, no key needed)
  - NewsAPI (free tier: 100/day)
  - Reddit API (free, requires app registration)
  - Twitter/X API (optional)

---

## Step 1: Prepare Raspberry Pi

### 1.1 Install Raspberry Pi OS

1. Download **Raspberry Pi Imager** - https://www.raspberrypi.com/software/
2. Insert MicroSD card into PC
3. Open Imager → Select:
   - **Device:** Raspberry Pi 5
   - **OS:** Raspberry Pi OS (64-bit) - Bookworm
   - **Storage:** MicroSD card
4. Click "Next" → Advanced options:
   - ✅ Set hostname: `crypto-pi`
   - ✅ Enable SSH
   - ✅ Set username/password (e.g., `pi` / `crypto123`)
   - ✅ Configure WiFi (if wireless)
5. Click "Write" and wait (~5 min)

### 1.2 Boot and Connect to Pi

1. Insert SD card into Pi
2. Power on and wait 2-3 minutes for first boot
3. SSH into Pi:
```bash
ssh pi@crypto-pi.local
# Or if that doesn't work:
ssh pi@<pi-ip-address>
```

### 1.3 Update System

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl wget htop
```

---

## Step 2: Copy Crypto Signal System to Pi

### Option A: Direct Copy via SCP (from dev machine)

On your development machine:
```bash
scp -r ~/OLC pi@crypto-pi.local:~/
```

### Option B: Clone from Git (if using GitHub)

On the Pi:
```bash
cd ~
git clone https://github.com/AasimKAI/OLC.git
cd OLC
git checkout main  # or your branch
```

### Option C: Manual Copy via Midnight Commander

```bash
ssh pi@crypto-pi.local
# Then use scp or copy files manually
```

**Verify the copy:**
```bash
ls -la ~/OLC/
# Should show: config/, collector/, analysts/, decision/, execution/, operations/, records/, tests/, main.py, README.md, etc.
```

---

## Step 3: Install Python Dependencies

```bash
cd ~/OLC

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Expected output:**
```
Successfully installed requests-2.31.0 pydantic-2.5.0 ...
```

**Verify installation:**
```bash
python3 -c "import requests; print(requests.__version__)"
```

---

## Step 4: Configure System

### 4.1 Edit Configuration

```bash
nano config/config.py
```

**Key settings to review/update:**

```python
# Operating mode
MODE = "testnet"  # Options: fixture, historical_replay, paper, testnet

# Tracked coins
TRACKED_COINS = ["BTC", "ETH", "XRP", "ADA", "SOL"]

# Intervals
COLLECTOR_INTERVAL = 300  # 5 minutes
VOLUME_SCAN_INTERVAL = 45  # 30-60 seconds
STATE_RECONCILIATION_ON_STARTUP = True

# Position sizing
POSITION_SIZE_USD = 100
MAX_EXPOSURE_USD = 500
BIG_TRADE_THRESHOLD_USD = 1000  # Requires Telegram approval

# Risk management
STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_TARGET_1_PERCENT = 5.0
REGIME_FILTER_ENABLED = True
REGIME_FILTER_STRICT = False  # Set True for trending-only mode

# LLM (Sentiment, Bull/Bear, CEO)
SENTIMENT_MODEL = "llama2"
SENTIMENT_TIMEOUT_SEC = 30  # Increase if on slower Pi

# Directories (update if needed for Pi paths)
LOG_DIR = "logs"
DATA_DIR = "data"
STATE_DIR = "state"

# Binance Testnet
BINANCE_TESTNET_BASE_URL = "https://testnet.binance.vision"

# Dashboard
DASHBOARD_PORT = 8000
DASHBOARD_LAN_MODE = False  # Set True to enable LAN access (requires auth)
DASHBOARD_AUTH_TOKEN = "your-secure-token-here"  # Generate random: openssl rand -hex 16
```

Press `Ctrl+X` → `Y` → `Enter` to save.

### 4.2 Configure Secrets

```bash
cp config/secrets.example.py config/secrets.py
nano config/secrets.py
```

**Fill in your API keys:**

```python
# BINANCE TESTNET (Required)
BINANCE_TESTNET_API_KEY = "your-testnet-api-key-from-testnet.binance.vision"
BINANCE_TESTNET_API_SECRET = "your-testnet-api-secret"

# OLLAMA LOCAL LLM (Required for sentiment analysis)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama2"  # Or "mistral", "neural-chat", etc.

# TELEGRAM (Optional, for big trade approvals)
TELEGRAM_BOT_TOKEN = "your-bot-token-from-botfather"  # Optional
TELEGRAM_CHAT_ID = "your-chat-id"  # Optional (find via @userinfobot)

# EXTERNAL APIs (Optional, free tiers work)
NEWSAPI_KEY = None  # Optional (https://newsapi.org)
REDDIT_CLIENT_ID = None  # Optional (create app at reddit.com/prefs/apps)
REDDIT_CLIENT_SECRET = None
REDDIT_USER_AGENT = "CryptoSignal/1.0"

# FX RATE (for tax ledger GBP conversion)
FX_RATE_SOURCE = "coingecko"  # Free, no key needed
```

**⚠️ CRITICAL:** `secrets.py` must NEVER be committed.

Verify it's in `.gitignore`:
```bash
cat .gitignore | grep secrets.py
# Should show: config/secrets.py
```

---

## Step 5: Install & Run Ollama (LLM)

The Sentiment Analyst and decision agents use Ollama for LLM inference.

### 5.1 Install Ollama

On Raspberry Pi:
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

Or manually:
```bash
wget https://ollama.ai/download/ollama-linux-arm64.tgz
tar -xzf ollama-linux-arm64.tgz
# Follow prompts
```

### 5.2 Start Ollama Service

```bash
# Start as background service
ollama serve &

# Or run in a separate terminal
ollama serve
```

**Expected output:**
```
2026-05-29T10:30:00.000Z INFO Using metal compute memory
2026-05-29T10:30:00.000Z INFO Available VRAM: 4096 MB
2026-05-29T10:30:00.000Z INFO Listening on 127.0.0.1:11434
```

### 5.3 Pull Model

```bash
ollama pull llama2
# Or lighter model if Pi memory is limited:
ollama pull mistral
ollama pull neural-chat
```

**Expected output:**
```
pulling 3f5e35e68d73...
pulling d6e75cbdf99e...
Done
```

### 5.4 Test Ollama

```bash
curl http://localhost:11434/api/generate -d '{
  "model": "llama2",
  "prompt": "Say hello",
  "stream": false
}'
```

Should return JSON with model response.

---

## Step 6: Test System (Before Running Live)

### 6.1 Run Test Suite

```bash
cd ~/OLC
python3 tests/run_tests.py
```

**Expected output:**
```
======================================================================
CRYPTO SIGNAL SYSTEM V4 - TEST SUITE
======================================================================
RESULTS: 40 passed, 0 failed
======================================================================
```

### 6.2 Test in Fixture Mode (No Network)

```bash
# In config/config.py, set:
MODE = "fixture"

# Run system for 1 minute (will use static test data)
timeout 60 python3 main.py

# Check output:
tail -20 logs/crypto_signal.log
```

### 6.3 Test in Paper Mode (Simulated, No Binance)

```bash
# In config/config.py, set:
MODE = "paper"

# Run for 5 minutes
timeout 300 python3 main.py

# Verify it processes feeds, analyzes, decides (no real orders)
tail -20 logs/crypto_signal.log
```

### 6.4 Verify Config

```bash
python3 -c "
from config.config import *
print(f'MODE: {MODE}')
print(f'TRACKED_COINS: {TRACKED_COINS}')
print(f'POSITION_SIZE_USD: {POSITION_SIZE_USD}')
print(f'Max Exposure: {MAX_EXPOSURE_USD}')
print('Config loaded successfully!')
"
```

---

## Step 7: Run on Binance Testnet

### 7.1 Verify Testnet Credentials

1. Go to https://testnet.binance.vision
2. Create/login to account
3. Generate API key:
   - Click "Generate HMAC_SHA256 Key"
   - ✅ Restrictions: **Spot Trading Only**
   - Copy **API Key** and **Secret Key**
4. Paste into `config/secrets.py`

### 7.2 Test Binance Connection

```bash
python3 -c "
from config.secrets import BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET
from execution.order_executor import OrderExecutor
from config.config import *

executor = OrderExecutor(__import__('types').SimpleNamespace(**{
    'BINANCE_TESTNET_BASE_URL': BINANCE_TESTNET_BASE_URL,
    'TAKER_FEE_PERCENT': TAKER_FEE_PERCENT
}))

print('Binance connection: OK')
print('Ready for testnet trading!')
"
```

### 7.3 Enable Testnet Mode

```bash
# In config/config.py:
MODE = "testnet"
```

### 7.4 Start System

```bash
cd ~/OLC
python3 main.py
```

**Expected output:**
```
2026-05-29 10:30:00 - __main__ - INFO - CryptoSignalSystem v4 initializing in mode: testnet
2026-05-29 10:30:00 - __main__ - INFO - Initializing layers...
2026-05-29 10:30:00 - __main__ - INFO - All layers initialized successfully
2026-05-29 10:30:00 - __main__ - INFO - Starting Crypto Signal System v4 in testnet mode...
2026-05-29 10:30:00 - operations.state_reconciler - INFO - Starting state reconciliation...
2026-05-29 10:30:00 - __main__ - INFO - System started. Running analysis/exit loops...
2026-05-29 10:30:05 - collector.collector - INFO - Collecting from coingecko...
2026-05-29 10:30:05 - collector.collector - INFO - Feed coingecko collected: 5 items
...
```

Press `Ctrl+C` to stop.

---

## Step 8: Run as Background Service (Persistent)

To keep the system running after SSH disconnect and restart:

### 8.1 Create Systemd Service

```bash
sudo nano /etc/systemd/system/crypto-signal.service
```

Paste this:

```ini
[Unit]
Description=Crypto Signal System v4
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/OLC
ExecStart=/usr/bin/python3 /home/pi/OLC/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Press `Ctrl+X` → `Y` → `Enter` to save.

### 8.2 Enable and Start Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable crypto-signal
sudo systemctl start crypto-signal

# Verify it's running
sudo systemctl status crypto-signal
```

**Expected output:**
```
● crypto-signal.service - Crypto Signal System v4
     Loaded: loaded (/etc/systemd/system/crypto-signal.service)
     Active: active (running) since Wed 2026-05-29 10:35:00 UTC
```

### 8.3 View Logs

```bash
# Real-time logs
sudo journalctl -u crypto-signal -f

# Last 50 lines
sudo journalctl -u crypto-signal -n 50

# Errors only
sudo journalctl -u crypto-signal | grep ERROR
```

### 8.4 Stop/Restart Service

```bash
sudo systemctl stop crypto-signal     # Stop
sudo systemctl restart crypto-signal  # Restart
sudo systemctl disable crypto-signal  # Disable on boot
```

---

## Step 9: Monitoring & Health Checks

### 9.1 Monitor System Health

```bash
# Check process is running
ps aux | grep main.py

# Check memory usage
free -h

# Check disk usage
df -h

# Check CPU temperature
vcgencmd measure_temp

# Monitor live
watch -n 2 'ps aux | grep main.py && free -h && df -h'
```

### 9.2 Check Decision Log

```bash
# View all decisions
cat ~/OLC/data/decision_log.jsonl | jq .

# Decisions for specific coin
cat ~/OLC/data/decision_log.jsonl | jq 'select(.coin == "BTC")'

# Count by status
cat ~/OLC/data/decision_log.jsonl | jq '.status' | sort | uniq -c
```

### 9.3 Check Tax Ledger

```bash
# View trades
cat ~/OLC/data/tax_ledger.jsonl | jq .

# Summary
cat ~/OLC/data/tax_ledger.jsonl | jq -s 'group_by(.coin) | map({coin: .[0].coin, trades: length})'
```

### 9.4 Check Kill Switch Status

```bash
# Is kill switch active?
cat ~/OLC/state/kill_switch.lock 2>/dev/null || echo "Kill switch OFF (system running)"
```

### 9.5 Heartbeat Check

```bash
# If heartbeat not working:
tail -20 ~/OLC/logs/crypto_signal.log | grep -i heartbeat
```

---

## Step 10: Validation Checklist

Before declaring deployment complete, verify:

### Pre-Deployment (Dev Machine)
- ✅ All 23 tests pass locally
- ✅ Config validated for Pi paths
- ✅ Secrets file NOT in git
- ✅ README and honest limits reviewed

### Initial Boot (First 10 minutes)
- ✅ System starts without errors
- ✅ Reconciliation completes (exchange state synced)
- ✅ First analysis cycle runs (logs show 7 feeds collected)
- ✅ No kill switch activated

### First Hour
- ✅ Multiple analysis cycles complete (5-min interval)
- ✅ Volume scans running (30-60s interval)
- ✅ Decision log has entries
- ✅ No repeated errors in logs
- ✅ CPU temp stays < 70°C

### First 24 Hours
- ✅ Heartbeat signals continuous (no long gaps)
- ✅ Watchdog restarting any failed components
- ✅ Ollama latency < 30s (sentiment analysis)
- ✅ Binance Testnet orders executing successfully
- ✅ Tax ledger recording trades correctly
- ✅ Telegram approvals working with `/approve <id>` and `/reject <id>` (if enabled)
- ⚠️ Dashboard implementation is not included yet; monitor logs and JSONL records

### 48+ Hour Stability Test
- ✅ System runs unattended for 48+ hours
- ✅ No crashes or hangs
- ✅ Decision quality consistent
- ✅ State reconciliation passes on restart
- ✅ Kill switch survives restart
- ✅ No orphaned orders on Binance

---

## Troubleshooting

### System Won't Start

```bash
# Check Python
python3 --version  # Should be 3.9+

# Check dependencies
pip list | grep requests

# Check config
python3 -c "from config.config import *; print(MODE)"

# Check secrets exist
ls -la config/secrets.py
```

### Ollama Not Responding

```bash
# Is Ollama running?
pgrep ollama || echo "Ollama not running"

# Start Ollama
ollama serve &

# Test endpoint
curl http://localhost:11434/api/tags

# Check model is downloaded
ollama list
```

### Binance Testnet Connection Fails

```bash
# Verify keys in config/secrets.py
grep BINANCE_TESTNET_API_KEY config/secrets.py

# Test network
ping testnet.binance.vision

# Check firewall
sudo ufw status
```

### High CPU/Memory Usage

```bash
# Check what's using resources
top -b -n 1

# Memory leak?
ps aux | grep main.py | awk '{print $6}'  # Check RSS

# Reduce update frequency
# In config/config.py: increase COLLECTOR_INTERVAL
```

### Logs Growing Too Fast

```bash
# Rotate logs
sudo logrotate /etc/logrotate.d/crypto-signal

# Or manually
gzip logs/crypto_signal.log
```

---

## Performance Tuning for Pi

### If System is Slow

1. **Reduce analysis frequency:**
   ```python
   # In config/config.py
   COLLECTOR_INTERVAL = 600  # 10 minutes (was 5)
   VOLUME_SCAN_INTERVAL = 120  # 2 minutes (was 45s)
   ```

2. **Use lighter LLM model:**
   ```python
   # In config/config.py
   SENTIMENT_MODEL = "neural-chat"  # Lighter than llama2
   # Pull: ollama pull neural-chat
   ```

3. **Reduce number of tracked coins:**
   ```python
   TRACKED_COINS = ["BTC", "ETH"]  # Fewer coins = faster analysis
   ```

4. **Disable non-essential feeds:**
   ```python
   FEED_CONFIG = {
       "coingecko": True,
       "news": False,      # Optional
       "reddit": False,    # Optional
       "twitter": False,   # Optional
   }
   ```

5. **Check Pi resources:**
   ```bash
   vcgencmd measure_clock arm     # CPU frequency
   vcgencmd measure_temp          # Temperature
   free -h                        # Memory usage
   ```

---

## Next Steps After Deployment

1. **Monitor for 48+ hours** - Ensure stability
2. **Review decision quality** - Are signals reasonable?
3. **Run edge validation** - Backtest signals on accumulated data
4. **Enable Telegram approvals** (if desired) - For big trades
5. **Document honest limits** - What was and wasn't tested on Pi
6. **Consider live trading** - Only after 4+ weeks of successful testnet operation

---

## Support & Monitoring

### Daily Checks

```bash
# Morning check
tail -100 logs/crypto_signal.log | grep -i error
tail -20 data/decision_log.jsonl
sudo systemctl status crypto-signal
```

### Weekly Reviews

```bash
# Decision quality
cat data/decision_log.jsonl | jq '.status' | sort | uniq -c

# Pi health
vcgencmd measure_temp
free -h
df -h
```

### Monthly

```bash
# Backup decision/tax logs
cp data/decision_log.jsonl backup/decision_log_$(date +%Y%m%d).jsonl
cp data/tax_ledger.jsonl backup/tax_ledger_$(date +%Y%m%d).jsonl
```

---

## Important Notes

⚠️ **Testnet Only** - This deployment uses Binance Testnet (fake money). Live trading is a separate decision made much later after extended validation.

⚠️ **No Guarantees** - The system is tested but untested on your specific Pi hardware. Monitor carefully.

⚠️ **API Keys** - Keep secrets.py secure. Never expose API keys in logs or public repos.

⚠️ **Tax Ledger** - Records are for audit purposes. Consult a tax professional before filing.

---

**Questions?** Review the README.md and Full Build Handoff for more context.

**Ready?** Start with Step 1 and follow each section in order.
