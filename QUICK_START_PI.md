# Quick Start - Raspberry Pi Deployment (5-Minute Summary)

**For detailed instructions, see `DEPLOYMENT_PI.md`**

## Prerequisites Checklist

- ✅ Raspberry Pi 5 (4GB+ RAM)
- ✅ MicroSD Card (32GB+)
- ✅ Power supply (5.1V/5A USB-C)
- ✅ Internet connection (Ethernet or WiFi)
- ✅ Binance Testnet account (https://testnet.binance.vision)

---

## 30-Second Installation

### On Your Development Machine

```bash
# Copy system to Pi
scp -r ~/OLC pi@crypto-pi.local:~/
```

### On Raspberry Pi

```bash
# SSH into Pi
ssh pi@crypto-pi.local

# Install Python dependencies
cd ~/OLC
pip install -r requirements.txt

# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve &
ollama pull llama2

# Configure
cp config/secrets.example.py config/secrets.py
nano config/secrets.py  # Add your Binance Testnet API keys

# Test
python3 tests/run_tests.py  # Should pass 23/23

# Run
python3 main.py
```

---

## Configuration (2 Files Only)

### 1. `config/config.py` - Settings

```python
MODE = "testnet"  # or: fixture, paper, historical_replay
TRACKED_COINS = ["BTC", "ETH"]
POSITION_SIZE_USD = 100
MAX_EXPOSURE_USD = 500
```

### 2. `config/secrets.py` - API Keys

```python
BINANCE_TESTNET_API_KEY = "your-key"
BINANCE_TESTNET_API_SECRET = "your-secret"
OLLAMA_BASE_URL = "http://localhost:11434"
```

**That's it!** No other files need editing.

---

## Modes Available

| Mode | Use Case | Internet | Binance | Ollama |
|------|----------|----------|---------|--------|
| **fixture** | Static test data | ❌ | ❌ | ❌ |
| **historical_replay** | Backtest on past data | ❌ | ❌ | ❌ |
| **paper** | Simulated trading | ✅ | ❌ | ❌ |
| **testnet** | Real Binance Testnet | ✅ | ✅ | ✅ |

Start with `fixture` or `paper` to test, then `testnet`.

---

## Running the System

### Option 1: Foreground (Debugging)

```bash
cd ~/OLC
python3 main.py

# Watch logs
tail -f logs/crypto_signal.log
```

Press `Ctrl+C` to stop.

### Option 2: Background Service (Production)

```bash
# Create service
sudo nano /etc/systemd/system/crypto-signal.service
# Paste config from DEPLOYMENT_PI.md (Step 8.1)

# Start
sudo systemctl start crypto-signal
sudo systemctl enable crypto-signal

# Monitor
sudo journalctl -u crypto-signal -f
```

---

## First-Time Checks (10 Minutes)

```bash
# 1. All tests pass?
python3 tests/run_tests.py
# → Expected: 37 passed, 0 failed

# 2. Config valid?
python3 -c "from config.config import *; print(f'Mode: {MODE}')"
# → Expected: Mode: testnet

# 3. Ollama running?
curl http://localhost:11434/api/tags
# → Expected: JSON with models list

# 4. System starts?
timeout 30 python3 main.py
# → Expected: Layers init, reconciliation, analysis starts

# 5. First cycle completes?
tail -20 logs/crypto_signal.log
# → Expected: feeds collected, analysis complete, decisions logged
```

---

## Daily Monitoring

```bash
# Check if running
ps aux | grep main.py

# View today's decisions
tail -50 data/decision_log.jsonl | jq '.decision, .coin'

# Check errors
grep ERROR logs/crypto_signal.log | tail -10

# System health
free -h
df -h
vcgencmd measure_temp
```

---

## Validation (What to Watch For)

### Hour 1
- ✅ System starts without errors
- ✅ Feeds collect (7 feeds)
- ✅ Analysis completes (RSI, Volume, etc.)
- ✅ Decisions logged

### Day 1
- ✅ 288 analysis cycles complete (5-min intervals × 24h)
- ✅ No kill switch activations
- ✅ Consistent decision quality
- ✅ Temperature < 70°C

### Week 1
- ✅ 48+ hour unattended run
- ✅ State reconciliation on restart passes
- ✅ Ollama latency < 30s
- ✅ Tax ledger accurate

---

## Troubleshooting (Common Issues)

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Ollama not responding | `ollama serve &` (ensure running) |
| Binance connection fails | Check API keys in `secrets.py`, verify testnet.binance.vision works |
| High CPU/Memory | Reduce `COLLECTOR_INTERVAL`, use lighter model, track fewer coins |
| Kill switch activated | Check logs: `tail logs/crypto_signal.log \| grep ERROR` |
| Service won't start | Check: `sudo systemctl status crypto-signal` |

---

## Performance Tips for Pi

```python
# If system is slow, in config/config.py:

# 1. Slower updates
COLLECTOR_INTERVAL = 600  # 10 min (was 5)
VOLUME_SCAN_INTERVAL = 120  # 2 min (was 45s)

# 2. Lighter model
SENTIMENT_MODEL = "neural-chat"  # Faster than llama2

# 3. Fewer coins
TRACKED_COINS = ["BTC", "ETH"]  # Not all 5

# 4. Monitor Pi
vcgencmd measure_temp
free -h
ps aux | grep main.py
```

---

## Next Steps

1. ✅ Deploy (follow 30-second install above)
2. ✅ Test in fixture mode (no network)
3. ✅ Test in paper mode (sim trades)
4. ✅ Run on testnet (real Binance Testnet)
5. ✅ Monitor for 48+ hours
6. ✅ Review decision quality
7. ✅ Consider live trading (only after 4+ weeks of success)

---

## Gotchas

⚠️ **Testnet Only** - Never put live money on this without months of validation

⚠️ **API Keys** - Keep `secrets.py` private, never commit to git

⚠️ **Ollama RAM** - Llama2 model needs ~4GB. If Pi stalls, use lighter model or increase swap

⚠️ **Backups** - Backup `data/decision_log.jsonl` and `data/tax_ledger.jsonl` weekly

---

## Filenames to Remember

```
config/config.py          ← Edit this (settings)
config/secrets.py         ← Edit this (API keys) - NEVER commit
logs/crypto_signal.log    ← Monitor this
data/decision_log.jsonl   ← Audit trail (decisions)
data/tax_ledger.jsonl     ← Tax records (GBP, trades)
DEPLOYMENT_PI.md          ← Full guide (read this if stuck)
```

---

## Need Help?

1. Read `DEPLOYMENT_PI.md` (detailed step-by-step)
2. Read `README.md` (features, modes, limits)
3. Read `Full Build Handoff` (what was tested, what wasn't)
4. Check logs: `tail -100 logs/crypto_signal.log`
5. Run tests: `python3 tests/run_tests.py`

---

**Ready to deploy?** Start with the 30-second installation above! 🚀
