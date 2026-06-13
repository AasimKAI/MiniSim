"""Shared helpers: logging, atomic writes, JSONL append, retry, time."""
import json, os, tempfile, time, logging, functools
from datetime import datetime, timezone

def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()

def get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(h)
    return logger

def atomic_write_json(path, obj):
    """Write JSON safely: temp file -> fsync -> rename. Survives crashes."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def append_jsonl(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())

def read_jsonl(path, limit=None):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows[-limit:] if limit else rows

def retry(times=2, delay=1.0, exceptions=(Exception,)):
    """Decorator: retry a function on failure."""
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            last = None
            for attempt in range(times + 1):
                try:
                    return fn(*a, **k)
                except exceptions as e:
                    last = e
                    if attempt < times:
                        time.sleep(delay * (attempt + 1))
            raise last
        return wrap
    return deco
