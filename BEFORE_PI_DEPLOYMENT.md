# Pre-Deployment Checklist for Raspberry Pi

Complete this checklist **before** moving the system to Raspberry Pi 5. This ensures all critical items are addressed and nothing is forgotten.

---

## Code & Tests (Development Machine)

### ✅ Code Quality

- [ ] All 23 tests pass locally
  ```bash
  python3 tests/run_tests.py
  # Expected: RESULTS: 23 passed, 0 failed
  ```

- [ ] No uncommitted changes
  ```bash
  git status
  # Expected: "working tree clean"
  ```

- [ ] Latest code pushed to main branch
  ```bash
  git log --oneline -5 origin/main
  git push origin main
  ```

- [ ] Code review completed (if applicable)
  - PR #1 reviewed and approved
  - All feedback addressed
  - PR merged to main

- [ ] No secrets in codebase
  ```bash
  grep -r "BINANCE.*KEY\|API.*KEY\|SECRET" --include="*.py" \
    | grep -v "example\|secrets.py"
  # Expected: No results (or only in templates/examples)
  ```

### ✅ Configuration Prepared

- [ ] `config/config.py` reviewed for Pi deployment
  - [ ] `MODE = "testnet"` (or appropriate mode)
  - [ ] `TRACKED_COINS` is reasonable (suggest: BTC, ETH)
  - [ ] `POSITION_SIZE_USD` is testnet-appropriate (suggest: 100)
  - [ ] `COLLECTOR_INTERVAL` is reasonable (suggest: 300 for Pi)
  - [ ] All paths are Pi-compatible (use relative paths)
  - [ ] `BINANCE_TESTNET_BASE_URL` is correct

- [ ] `config/secrets.example.py` is correct template
  - [ ] No real keys in example file
  - [ ] All required fields are present
  - [ ] Comments are clear

- [ ] `.gitignore` includes `config/secrets.py`
  ```bash
  cat .gitignore | grep secrets.py
  # Expected: config/secrets.py
  ```

### ✅ Documentation Complete

- [ ] README.md updated and comprehensive
  - [ ] Architecture explained
  - [ ] Installation steps clear
  - [ ] Configuration documented
  - [ ] Honest limits stated

- [ ] DEPLOYMENT_PI.md is complete and tested
  - [ ] All 10 steps documented
  - [ ] Commands tested (or clearly noted if untested)
  - [ ] Troubleshooting section complete

- [ ] QUICK_START_PI.md matches DEPLOYMENT_PI.md
  - [ ] 30-second setup is accurate
  - [ ] Key commands are correct

- [ ] COLLABORATOR_GUIDE.md explains workflow
  - [ ] Branching strategy documented
  - [ ] PR process documented
  - [ ] Security guidelines stated

- [ ] Inline code comments are present
  - [ ] Non-obvious logic is commented
  - [ ] All layers have docstrings
  - [ ] Complex functions explained

---

## Secrets & Credentials (Pre-Pi Setup)

### ✅ Binance Testnet Account

- [ ] Account created at https://testnet.binance.vision
- [ ] Logged in successfully
- [ ] API key generated
  - [ ] Restrictions set to **SPOT TRADING ONLY**
  - [ ] NO withdrawal permissions
  - [ ] Key saved securely (password manager recommended)
- [ ] API Secret saved securely
- [ ] Test with mock call (optional):
  ```bash
  curl -X GET "https://testnet.binance.vision/api/v3/account" \
    -H "X-MBX-APIKEY: your-api-key"
  # Should return account info (or auth error if key is wrong)
  ```

### ✅ Ollama Setup (Validated Locally)

- [ ] Ollama installed and running on dev machine
  ```bash
  ollama serve
  # Should show: "Listening on 127.0.0.1:11434"
  ```

- [ ] Model pulled successfully
  ```bash
  ollama pull llama2
  # Or: ollama pull mistral (if lighter model preferred)
  ```

- [ ] Model responds to test query
  ```bash
  curl http://localhost:11434/api/generate -d '{
    "model": "llama2",
    "prompt": "Say hello",
    "stream": false
  }'
  # Should return JSON with response
  ```

- [ ] Model size checked (for Pi storage)
  ```bash
  ollama list
  # Note model size (llama2 ~4GB, mistral ~4GB, neural-chat ~3GB)
  ```

### ✅ Optional: Telegram Setup

- [ ] Telegram bot created (optional, for big trade approvals)
  - [ ] Chatted with @BotFather
  - [ ] Created new bot
  - [ ] Got bot token
  - [ ] Noted bot username

- [ ] Telegram Chat ID found (optional)
  - [ ] Chatted with @userinfobot
  - [ ] Got your numeric chat ID

- [ ] Credentials saved securely
  - [ ] NOT in git
  - [ ] Will be entered in `config/secrets.py`

---

## Environment Validation (Dev Machine)

### ✅ Python & Dependencies

- [ ] Python version correct
  ```bash
  python3 --version
  # Expected: 3.9 or higher
  ```

- [ ] Virtual environment created (recommended)
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

- [ ] All dependencies installed
  ```bash
  pip install -r requirements.txt
  pip list | grep -E "requests|pydantic"
  # Should show installed packages
  ```

- [ ] Import test passes
  ```bash
  python3 -c "
  from config.config import *
  from collector.collector import Collector
  from analysts.technical_analyst import TechnicalAnalyst
  from decision.ceo_agent import CEOAgent
  from execution.risk_manager import RiskManager
  from operations.state_reconciler import StateReconciler
  from records.decision_log import DecisionLog
  print('All imports OK!')
  "
  ```

### ✅ Mode Testing

- [ ] **Fixture mode** tested (no network)
  ```bash
  # In config/config.py: MODE = "fixture"
  timeout 30 python3 main.py
  # Should complete without network errors
  ```

- [ ] **Paper mode** tested (simulated)
  ```bash
  # In config/config.py: MODE = "paper"
  timeout 60 python3 main.py
  # Should collect feeds and simulate analysis
  ```

- [ ] **Testnet mode** tested locally (if possible)
  ```bash
  # In config/config.py: MODE = "testnet"
  # With valid secrets.py
  timeout 60 python3 main.py
  # Should reconcile state and attempt first cycle
  ```

- [ ] Tests pass in all modes
  ```bash
  python3 tests/run_tests.py
  # Expected: 23 passed regardless of mode
  ```

---

## Hardware Preparation (Pi Setup)

### ✅ Raspberry Pi Hardware

- [ ] **Raspberry Pi 5** ready
  - [ ] Model: Pi 5 (check with `uname -m`)
  - [ ] RAM: 4GB minimum, 8GB recommended
  - [ ] Power supply: 5.1V/5A USB-C
  - [ ] MicroSD card: 32GB+ formatted

- [ ] **OS Installed**
  - [ ] Raspberry Pi OS Bookworm (64-bit)
  - [ ] Latest updates: `sudo apt update && sudo apt upgrade`
  - [ ] Git installed: `git --version` (2.34+)

- [ ] **Network Verified**
  - [ ] Ethernet or WiFi connected
  - [ ] `ping google.com` successful
  - [ ] Latency < 50ms (check with `ping -c 5 testnet.binance.vision`)

- [ ] **Storage Verified**
  ```bash
  df -h
  # Root filesystem should have 10GB+ free
  ```

- [ ] **Hardware Specs Confirmed**
  ```bash
  cat /proc/cpuinfo | grep "model name"  # CPU
  free -h                                 # RAM
  vcgencmd get_config int gpu_mem        # GPU memory
  ```

### ✅ SSH Access

- [ ] SSH enabled on Pi
  - [ ] Connected: `ssh pi@crypto-pi.local`
  - [ ] Can execute commands remotely
  - [ ] SCP works: `scp -r ~/OLC pi@crypto-pi.local:~/`

- [ ] SSH keys configured (optional but recommended)
  ```bash
  ssh-keygen -t ed25519
  ssh-copy-id -i ~/.ssh/id_ed25519.pub pi@crypto-pi.local
  ```

---

## Pre-Deployment Testing Checklist

### ✅ Run All Tests One Final Time

```bash
cd ~/OLC
python3 tests/run_tests.py
```

- [ ] All 23 tests pass
- [ ] No warnings or deprecations
- [ ] Test output clean

### ✅ Simulate Pi Directory Structure

```bash
# Verify relative paths work from different directory
cd /tmp
python3 ~/OLC/main.py --help  # If help exists
# Or just verify imports:
python3 -c "import sys; sys.path.insert(0, '~/OLC'); from main import CryptoSignalSystem"
```

### ✅ Check Log Output Format

```bash
# Run briefly and check logs are written correctly
timeout 10 python3 main.py
ls -lh logs/
cat logs/crypto_signal.log | head -20
```

- [ ] Logs created in `logs/` directory
- [ ] Format is readable JSON/text
- [ ] No excessive file size

---

## Security Review

### ✅ Secrets Management

- [ ] `config/secrets.py` NOT committed to git
  ```bash
  git log --all -- config/secrets.py
  # Expected: No results (file never committed)
  ```

- [ ] `config/secrets.example.py` has no real credentials
  ```bash
  grep -i "binance\|telegram\|reddit" config/secrets.example.py \
    | grep -v "your-\|example\|template"
  # Expected: No real credentials
  ```

- [ ] Binance keys are TRADE-ONLY
  - [ ] Verified in Binance Testnet account settings
  - [ ] No withdrawal permission
  - [ ] Noted in README

- [ ] Secrets file permissions restricted
  ```bash
  chmod 600 config/secrets.py  # Only owner can read
  ```

### ✅ Code Security

- [ ] No hardcoded credentials anywhere
  ```bash
  grep -r "BINANCE.*=\|API_KEY\|SECRET" --include="*.py" \
    | grep -v "config/\|example\|#"
  # Expected: No results (except in config/)
  ```

- [ ] Input validation present
  - [ ] Config fields validated on startup
  - [ ] API responses validated before use
  - [ ] No shell injection vulnerabilities

- [ ] Error handling doesn't leak secrets
  ```bash
  grep -A 5 "except.*:" main.py | grep -i "print\|log"
  # Verify no exception details are logged
  ```

---

## Operational Readiness

### ✅ Monitoring Plan

- [ ] Log location known: `~/OLC/logs/crypto_signal.log`
- [ ] Decision log location known: `~/OLC/data/decision_log.jsonl`
- [ ] Tax ledger location known: `~/OLC/data/tax_ledger.jsonl`
- [ ] Health check command known:
  ```bash
  ps aux | grep main.py
  tail -20 ~/OLC/logs/crypto_signal.log
  ```

### ✅ Backup Plan

- [ ] Backup location identified (external drive, cloud, etc.)
- [ ] Backup script prepared (if automated):
  ```bash
  # Backup decision logs weekly
  rsync -av ~/OLC/data/ /backup/crypto-signal-$(date +%Y%m%d)/
  ```
- [ ] Restore procedure documented

### ✅ Restart Plan

- [ ] Systemd service file prepared (if running as service)
- [ ] Restart command known: `sudo systemctl restart crypto-signal`
- [ ] Stop command known: `sudo systemctl stop crypto-signal`
- [ ] Log check after restart: `sudo journalctl -u crypto-signal -n 50`

### ✅ Escalation Plan

- [ ] Who to contact if system fails
- [ ] How to report issues (GitHub issues)
- [ ] How to request help
- [ ] How to disable system if needed (kill switch)

---

## Final Pre-Deployment Review

### ✅ Sign-Off Checklist

Before deploying to Pi, confirm:

- [ ] All tests pass (23/23)
- [ ] Code reviewed (no secrets)
- [ ] Config prepared for Pi
- [ ] Documentation complete
- [ ] Secrets secured
- [ ] Hardware ready
- [ ] SSH working
- [ ] Binance Testnet account ready
- [ ] Ollama model downloaded
- [ ] Monitoring plan documented
- [ ] Backup plan ready
- [ ] Restart procedures documented

### ✅ Deployment Sign-Off

```
Deployer: _____________________
Date: _____________________
All checks completed: YES / NO
Ready for Pi deployment: YES / NO
```

---

## Deployment Execution (Next Step)

Once all items above are checked, follow:

1. **QUICK_START_PI.md** - 30-minute deployment
2. **DEPLOYMENT_PI.md** - Detailed step-by-step guide
3. **Validation Checklists** - Post-deployment verification

---

## Post-Deployment (After Pi is Running)

After deploying to Pi, complete:

- [ ] **1-hour validation** (Step 10.1 in DEPLOYMENT_PI.md)
- [ ] **24-hour validation** (Step 10.2)
- [ ] **48-hour stability test** (Step 10.3)

If all pass, system is production-ready for extended Testnet operation!

---

## Issues During Deployment?

If you encounter problems during deployment:

1. **Check logs first:**
   ```bash
   tail -50 ~/OLC/logs/crypto_signal.log
   grep ERROR ~/OLC/logs/crypto_signal.log
   ```

2. **Review troubleshooting:**
   - DEPLOYMENT_PI.md → Troubleshooting section
   - README.md → Troubleshooting section

3. **Report issue:**
   - GitHub: https://github.com/AasimKAI/OLC/issues
   - Include: error message, command run, config (no secrets!)

---

**Ready to deploy?** Check all boxes above, then proceed to QUICK_START_PI.md! 🚀
