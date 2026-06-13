"""
v5 Quantized LLM client.

Runs a small GGUF quantized model on-device with llama-cpp-python — no Ollama,
no Docker, no external server. Tuned for Raspberry Pi 5 (16GB) + NVMe.

Three backends, chosen by config.LLM_BACKEND:
  llamacpp  -> load the GGUF model locally (recommended)
  ollama    -> talk to an Ollama server (kept for backwards compatibility)
  stub      -> deterministic offline responses (used in tests / when no model)

If the chosen backend fails for any reason, the client degrades safely to the
deterministic stub rather than crashing the trading system.
"""
import json, re, time, threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout
from config import config
from common import get_logger

log = get_logger("llm")

_LLAMA = None  # lazy singleton so the heavy model loads only once
_EXEC = ThreadPoolExecutor(max_workers=1)  # at most one inference at a time
_INFLIGHT = None                              # the currently-running inference
_GATE = threading.Lock()                      # guards _INFLIGHT bookkeeping


def _load_llamacpp():
    global _LLAMA
    if _LLAMA is not None:
        return _LLAMA
    from llama_cpp import Llama  # imported lazily; only needed for this backend
    import os
    path = os.path.abspath(config.LLM_MODEL_PATH)
    if not os.path.exists(path):
        raise FileNotFoundError(f"GGUF model not found at {path}")
    log.info("Loading quantized model: %s", path)
    _LLAMA = Llama(
        model_path=path,
        n_ctx=config.LLM_CONTEXT_TOKENS,
        n_threads=config.LLM_THREADS,
        n_gpu_layers=0,        # Pi has no CUDA GPU; CPU inference
        verbose=False,
    )
    return _LLAMA


def _chat_llamacpp(system, user):
    llm = _load_llamacpp()
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
    )
    return out["choices"][0]["message"]["content"]


def _chat_ollama(system, user):
    import httpx
    from config import secrets  # noqa
    base = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
    model = getattr(config, "SENTIMENT_MODEL", "llama2")
    r = httpx.post(
        f"{base}/api/chat",
        json={"model": model, "stream": False,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=config.LLM_TIMEOUT_SEC,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _chat_stub(system, user):
    """Deterministic, safe, offline. Always abstains / neutral."""
    return json.dumps({
        "verdict": "neutral",
        "confidence": 0.0,
        "reasoning": "LLM unavailable — deterministic safe fallback (stand down).",
    })


def _extract_json(text):
    """Pull the first {...} JSON object out of model output."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


def chat_json(system, user, schema_keys=("verdict", "confidence", "reasoning")):
    """
    Run the LLM and return a validated dict. Never raises to the caller —
    on any failure it returns a safe neutral/abstain result so the trading
    system stands down rather than acting on garbage.
    """
    backends = {"llamacpp": _chat_llamacpp, "ollama": _chat_ollama, "stub": _chat_stub}
    fn = backends.get(config.LLM_BACKEND, _chat_llamacpp)

    # Fail fast (no retry storm) if the quantized model file simply isn't there.
    if config.LLM_BACKEND == "llamacpp":
        import os as _os
        if not _os.path.exists(_os.path.abspath(config.LLM_MODEL_PATH)):
            out = json.loads(_chat_stub(system, user))
            out["_backend"] = "fallback(no-model)"
            out["_latency_sec"] = 0.0
            return out

    # SINGLE-FLIGHT, TIME-BOXED: never queue behind a stuck inference. If the
    # one worker is already busy (a prior call that hasn't finished), or this
    # call exceeds the time budget, return the safe neutral fallback immediately
    # rather than stalling the caller or piling up abandoned work.
    global _INFLIGHT
    with _GATE:
        busy = _INFLIGHT is not None and not _INFLIGHT.done()
        if busy:
            return _fallback("busy")
        fut = _EXEC.submit(fn, config_prompt_guard(system), user)
        _INFLIGHT = fut
    try:
        t0 = time.time()
        raw = fut.result(timeout=config.LLM_TIMEOUT_SEC)
        data = _extract_json(raw)
        for k in schema_keys:
            data.setdefault(k, None)
        if data.get("confidence") is None:
            data["confidence"] = 0.0
        data["confidence"] = max(0.0, min(1.0, float(data["confidence"])))
        data["_latency_sec"] = round(time.time() - t0, 2)
        data["_backend"] = config.LLM_BACKEND
        return data
    except _FTimeout:
        log.warning("LLM timed out after %ss; safe fallback (worker freed for later calls)",
                    config.LLM_TIMEOUT_SEC)
        return _fallback("timeout")
    except Exception as e:  # noqa: BLE001
        log.warning("LLM call failed: %s; safe fallback", e)
        return _fallback("error")


def _fallback(reason):
    out = json.loads(_chat_stub("", ""))
    out["_backend"] = f"fallback({reason})"
    out["_latency_sec"] = 0.0
    return out


def config_prompt_guard(system):
    """Append a hard instruction to always return strict JSON."""
    return (system +
            "\n\nRespond ONLY with a single minified JSON object. "
            "No prose, no markdown. Keys: verdict (bullish|bearish|neutral), "
            "confidence (0.0-1.0 number), reasoning (short string).")


def healthcheck():
    """Quick check used by the dashboard / startup."""
    try:
        if config.LLM_BACKEND == "llamacpp":
            import os
            ok = os.path.exists(os.path.abspath(config.LLM_MODEL_PATH))
            return {"backend": "llamacpp", "model_present": ok,
                    "model_path": config.LLM_MODEL_PATH}
        return {"backend": config.LLM_BACKEND, "model_present": True}
    except Exception as e:  # noqa
        return {"backend": config.LLM_BACKEND, "model_present": False, "error": str(e)}
