# MiniSim v5 — Plain-English Setup Guide

This guide assumes **no coding knowledge**. Follow it top to bottom. Every command
is something you copy and paste into the Pi's black "Terminal" window, then press Enter.

Everything runs in **paper mode** by default — that means **pretend money only**.
You can watch it work for as long as you like before risking anything real.

---

## What you need
- Your Raspberry Pi 5 (16GB) with the NVMe SSD, powered on and connected to your Wi-Fi.
- A keyboard/screen on the Pi, *or* the ability to "SSH" in from your laptop (optional).
- About 20 minutes, mostly waiting for downloads.

---

## The one-click way (recommended)

1. **Copy the `MiniSim` folder onto your Pi** (e.g. into your home folder). If you
   downloaded a zip, right-click it and choose *Extract Here*.

2. **Open the folder, then double-click `install.sh`.** When the Pi asks, choose
   **"Execute in Terminal"**. (If you don't see that option, double-click
   `MiniSim-Setup.desktop` instead, or open a Terminal in the folder and type
   `bash install.sh`.)

3. **Wait.** The installer does everything for you: installs what's needed, builds
   the Python environment, downloads the on-device AI model (~2GB, one time),
   runs a self-test, sets the app to start automatically on boot, and puts three
   shortcuts on your Desktop. It may ask for your password once (that's normal) and
   can take 10–20 minutes, mostly downloads.

4. **When it finishes** it prints the two web addresses and creates Desktop icons:
   - **MiniSim Dashboard** — opens the Pi screen view.
   - **Start MiniSim** / **Stop MiniSim** — start or stop trading.

That's it. It runs in **paper mode** (pretend money) — nothing real is traded.

### Opening the dashboards
- **On the Pi's own screen:** double-click **MiniSim Dashboard**, or open the
  browser at `http://localhost:8770/pi` (the big, simple kiosk view).
- **On your phone** (same Wi-Fi): the installer printed an address like
  `http://192.168.1.42:8770` — open that in your phone's browser for the
  mobile-friendly view. The red **KILL SWITCH** button stops trading instantly.

If a dashboard ever says *offline*, the engine isn't running — double-click
**Start MiniSim**.

---

## When you're ready to use the real test exchange (still fake money)

Full details of every account type (spot testnet, futures testnet for shorts,
Hyperliquid, live) and key-safety rules are in **[ACCOUNTS.md](ACCOUNTS.md)**.
The short version for longs-only testnet:

1. Make a free account at https://testnet.binance.vision and create API keys.
2. Copy the secrets template and paste your keys in:
   ```
   cp config/secrets.example.py config/secrets.py
   nano config/secrets.py
   ```
   (Use the arrow keys, paste your keys between the quotes, then press
   Ctrl+O, Enter to save and Ctrl+X to exit.)
3. In `config/config.py`, change the line `MODE = ... "paper"` to `"testnet"`.
4. Restart the engine.

**Do not switch to `"live"` (real money) until you have run in testnet for weeks and
fully understand the behaviour.** This software comes with no warranty.

---

## Quick troubleshooting
- **A dashboard says "offline":** the engine window probably isn't running. Restart Step 4.
- **"LLM" pill is red on the dashboard:** the AI model file is missing — re-run Step 3.
- **Everything says STAND_DOWN forever:** that's fine and expected when markets are
  quiet. The system is deliberately cautious.
- **You want to stop everything right now:** press the KILL SWITCH on the dashboard, or
  close the engine Terminal window.

If you get stuck, the most useful thing to share for help is the last 20 lines printed
in the engine Terminal window.
