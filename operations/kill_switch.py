"""Layer E — kill switch. Survives restart (a lock file on disk).
Robust to filesystems where deleting a file is restricted: 'inactive' is
represented by the file being absent OR empty.

Semantics (v7): the kill switch blocks NEW entries (run_cycle). Protective
exits — stop-loss, take-profit, trailing, max-hold — keep running so open
positions are never left unmanaged."""
import os
from config import config

def is_active():
    try:
        with open(config.KILL_SWITCH_FILE) as f:
            return bool(f.read().strip())
    except FileNotFoundError:
        return False

def activate(reason="manual"):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(config.KILL_SWITCH_FILE, "w") as f:
        f.write(reason or "activated")

def deactivate():
    try:
        os.remove(config.KILL_SWITCH_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        # fall back: blank the file so is_active() reports inactive
        with open(config.KILL_SWITCH_FILE, "w") as f:
            f.write("")
