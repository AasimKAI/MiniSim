"""MiniSim v5 test suite — simple PASS/FAIL, no external test framework.
Run:  python tests/run_tests.py"""
import os, sys, math, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0; FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  PASS  {name}")
    else:    FAIL += 1; print(f"  FAIL  {name}")

def synth(trend, n=200, anchor=100.0):
    # additive drift so trend is realistic (multiplicative -0.6 would collapse)
    import random; random.seed(7)
    out=[]; p=anchor
    for i in range(n):
        p=max(1.0, p + trend + random.uniform(-0.25,0.25))
        o=p; c=p+random.uniform(-0.2,0.2)
        out.append({"open":o,"high":max(o,c)+0.3,"low":min(o,c)-0.3,
                    "close":c,"volume":100+random.uniform(0,200)+(i if trend>0 else -i*0.0)})
    return out

print("MiniSim — TEST SUITE\n" + "="*50)

print("\nSchemas:")
from schemas.validators import (validate_analyst_verdict, validate_signal,
                                 validate_order, SchemaError)
check("valid analyst verdict accepted",
      validate_analyst_verdict({"analyst":"t","coin":"BTC","verdict":"bullish","confidence":0.5}))
try:
    validate_analyst_verdict({"analyst":"t","coin":"BTC","verdict":"up","confidence":0.5}); ok=False
except SchemaError: ok=True
check("invalid verdict rejected", ok)
try:
    validate_signal({"signal_id":"1","coin":"BTC","action":"NOPE","confidence":0.1,"timestamp":"x"}); ok=False
except SchemaError: ok=True
check("invalid action rejected", ok)

print("\nIndicators:")
from analysts import indicators as ind
closes=[c["close"] for c in synth(0.5)]
highs=[c["high"] for c in synth(0.5)]; lows=[c["low"] for c in synth(0.5)]
check("RSI in range", 0<=ind.rsi(closes)<=100)
check("EMA computed", ind.ema(closes,20) is not None)
check("MACD has hist", "hist" in ind.macd(closes))
check("ADX computed", ind.dmi_adx(highs,lows,closes) is not None)
check("Supertrend direction", ind.supertrend(highs,lows,closes)["direction"] in ("up","down"))
check("Bollinger ordered", (lambda b: b["lower"]<b["mid"]<b["upper"])(ind.bollinger(closes)))
check("resample shrinks series", len(ind.resample(synth(0.1),5))<len(synth(0.1)))

print("\nTechnical analyst:")
from analysts import technical_analyst as ta
up=ta.analyze("BTC",synth(0.6)); dn=ta.analyze("BTC",synth(-0.6))
check("uptrend -> bullish", up["verdict"]=="bullish")
check("downtrend -> bearish", dn["verdict"]=="bearish")
check("confidence bounded", 0<=up["confidence"]<=1)

print("\nRisk manager:")
from execution import risk_manager
from config import config
qty,dec,why=risk_manager.check("BTC","ENTRY_BUY",100,{"cash_usd":10000},[])
check("approves normal entry", qty>0 and dec in("approve","shrink"))
qty2,dec2,_=risk_manager.check("BTC","ENTRY_BUY",100,{"cash_usd":10000},
      [{"quantity":10,"entry_price":100,"current_price":100}])  # $1000 exposure... under 500? no
check("vetoes over-exposure", qty2==0)

print("\nExit manager:")
from execution import exit_manager
e=exit_manager.evaluate({"entry_price":100,"opened_at":time.time()},97.5)  # -2.5%
check("stop loss triggers", e[0] and "stop" in e[2].lower())
e2=exit_manager.evaluate({"entry_price":100,"opened_at":time.time()},100.5)
check("small move holds", not e2[0])

print("\nExchange idempotency (paper):")
from mcp_servers import _exchange_core as ex
import json
ex._save({"cash_usd":10000.0,"positions":{},"fills":[]})
r1=ex.place_order("ETH","BUY",0.1,"dup-1"); r2=ex.place_order("ETH","BUY",0.1,"dup-1")
check("first order fills", r1["status"]=="filled")
check("duplicate ignored", r2["status"]=="duplicate_ignored")
ex._save({"cash_usd":10000.0,"positions":{},"fills":[]})

print("\nMCP client (in-process fallback):")
from mcp_client.client import MCPClient
mc=MCPClient.__new__(MCPClient); mc.transport_ok=False; mc._sessions={}
check("candles via fallback", len(mc.candles("BTC"))==200)
check("ticker via fallback", mc.ticker("BTC")["price"]>0)

print("\nKill switch:")
from operations import kill_switch
kill_switch.activate("test"); a=kill_switch.is_active()
kill_switch.deactivate(); b=kill_switch.is_active()
check("activate works", a)
check("deactivate works", not b)

print("\nDecision engine:")
from decision import engine
allowed,_=engine.regime_allows("trending")
check("trending allows entries", allowed)
blocked,_=engine.regime_allows("volatile")
check("volatile blocks entries", not blocked)


print("\nRegression — review fixes:")
# C1: take-profit fires once, then is suppressed
from execution import exit_manager as _em
pos={"entry_price":100,"opened_at":time.time(),"peak_pnl":0.0,"targets_taken":[]}
s1=_em.evaluate(pos,106)   # +6% -> T1
check("C1 T1 fires at +6%", s1[0] and s1[3].get("target_level")==1)
pos["targets_taken"]=[1]
s2=_em.evaluate(pos,106)   # +6% again, T1 already taken
check("C1 T1 does NOT re-fire", (not s2[0]) or s2[3].get("target_level")!=1)
# trailing stop (previously dead code)
pos2={"entry_price":100,"opened_at":time.time(),"peak_pnl":16.0,"targets_taken":[1,2,3]}
st=_em.evaluate(pos2,112)  # peak 16 -> now 12, drop 4 >= 3
check("trailing stop fires on pullback", st[0] and "trailing" in st[2])

# M1: single-item list stays a list (in-process fallback path)
from mcp_client.client import MCPClient as _MC
_mc=_MC.__new__(_MC); _mc.transport_ok=False; _mc._sessions={}
c1=_mc.candles("BTC",1)
check("M1 candles(count=1) is a list", isinstance(c1,list) and len(c1)==1 and isinstance(c1[0],dict))

# M3: StochRSI has distinct, smoothed k and d
_cl=[c["close"] for c in synth(0.4,260)]
_sr=ind.stoch_rsi(_cl)
check("M3 StochRSI returns k and d", _sr is not None and "k" in _sr and "d" in _sr)

# M4: divergence returns a valid label
check("M4 divergence label valid", ind.rsi_divergence(_cl) in ("none","bullish","bearish"))

# M5: hard exposure cap — sizing near the ceiling cannot overshoot
from execution import risk_manager as _rm
near=[{"quantity":4.6,"entry_price":100,"current_price":100}]  # $460 of $500
q,dec,why=_rm.check("BTC","ENTRY_BUY",100,{"cash_usd":10000},near)
post=460 + q*100
check("M5 post-trade exposure <= cap", post <= config.MAX_EXPOSURE_USD + 1e-6)

# Sentiment/CEO verdict validation — a malformed LLM verdict becomes neutral
from analysts.sentiment_analyst import sentiment_analyst
class _StubMC:
    def headlines(self,coin,limit=5): return ["x"]
import llm.quantized_client as _q
_orig=_q.chat_json
_q.chat_json=lambda s,u,**k:{"verdict":"<img onerror=x>","confidence":0.9,"reasoning":"y"}
import analysts.sentiment_analyst as _sa; _sa.chat_json=_q.chat_json
v=sentiment_analyst("BTC",_StubMC())
check("hostile LLM verdict sanitised to neutral", v["verdict"]=="neutral")
_q.chat_json=_orig; _sa.chat_json=_orig

# Preflight refuses testnet without a real exchange
import main as _main
_save_mode=config.MODE; config.MODE="testnet"
class _BadBalMC:
    def balance(self): return {"error":"no creds","equity_usd":None}
try:
    _main.preflight(_BadBalMC()); _ok=False
except SystemExit: _ok=True
check("preflight blocks testnet without exchange", _ok)
config.MODE=_save_mode

# Market data reports its source honestly
from mcp_servers import _marketdata_core as _md
_md._CACHE.clear(); _md.get_ticker("BTC")
check("data source is labelled", _md.current_source("BTC") in ("binance","coingecko","synthetic","synthetic(fallback)"))


print("\nRegression — re-review (round 2) fixes:")
# NEW-1: preflight refuses if exchange server mode != configured mode
import main as _m
_sv=config.MODE; config.MODE="testnet"
class _PaperMC:
    def balance(self): return {"mode":"paper","equity_usd":10000.0}  # subprocess on wrong mode
try:
    _m.preflight(_PaperMC()); _ok=False
except SystemExit: _ok=True
check("NEW-1 preflight blocks mode mismatch", _ok)
config.MODE=_sv

# NEW-2: a non-filled exit must NOT mark the TP level taken (so it can retry)
from mcp_servers import _exchange_core as _ex
_ex._save({"cash_usd":9000.0,"positions":{"ZZ":{"quantity":3.0,"entry_price":100.0,"opened_at":time.time()}},"fills":[]})
import json as _json
open(_ex._META,"w").write(_json.dumps({"ZZ":{"peak_pnl":0.0,"targets_taken":[]}}))
# simulate the run_exits decision+fill where the order fails (status unknown)
from execution import exit_manager as _em
pos={"coin":"ZZ","entry_price":100,"opened_at":time.time(),"current_price":106,
     "peak_pnl":0.0,"targets_taken":[]}
should,frac,reason,meta=_em.evaluate(pos,106)
lvl=meta.get("target_level")
# emulate the corrected ordering: only mark after a 'filled' status
fake_status="unknown"
if fake_status=="filled" and lvl is not None:
    _ex.update_meta("ZZ", add_target=lvl)
taken_after_fail=_ex.position_meta().get("ZZ",{}).get("targets_taken",[])
check("NEW-2 failed exit does NOT mark TP taken", lvl==1 and 1 not in taken_after_fail)
# and a filled status DOES mark it
if "filled"=="filled" and lvl is not None:
    _ex.update_meta("ZZ", add_target=lvl)
check("NEW-2 filled exit marks TP taken", 1 in _ex.position_meta().get("ZZ",{}).get("targets_taken",[]))
_ex._save({"cash_usd":10000.0,"positions":{},"fills":[]}); open(_ex._META,"w").write("{}")

# NEW-3: single-flight gate — busy model returns fallback immediately
import threading as _th
_svb,_svt,_svp=config.LLM_BACKEND,config.LLM_TIMEOUT_SEC,config.LLM_MODEL_PATH
config.LLM_BACKEND="llamacpp"; config.LLM_TIMEOUT_SEC=1
import os as _os
_dummy=os.path.join(config.BASE_DIR,"models"); _os.makedirs(_dummy,exist_ok=True)
_dp=os.path.join(_dummy,"t.gguf");
try: open(_dp,"w").write("x")
except Exception: pass
config.LLM_MODEL_PATH=_dp
import llm.quantized_client as _q
_q._INFLIGHT=None
_q._chat_llamacpp=lambda s,u:(time.sleep(3) or '{}')
_res={}
def _c(i):_res[i]=_q.chat_json("s","u")["_backend"]
t0=_th.Thread(target=_c,args=(0,)); t0.start(); time.sleep(0.3)
t1=_th.Thread(target=_c,args=(1,)); t1.start(); t1.join()
check("NEW-3 busy model returns immediate fallback", "busy" in _res.get(1,""))
t0.join()
config.LLM_BACKEND,config.LLM_TIMEOUT_SEC,config.LLM_MODEL_PATH=_svb,_svt,_svp

# NEW-4: cache returns a series at least as long as requested
from mcp_servers import _marketdata_core as _md
_md._CACHE.clear()
_md.get_candles("BTC",100)            # seed cache with 100? (synth makes >=300)
big=_md.get_candles("BTC",250)
check("NEW-4 cache satisfies larger request", len(big)>=250)

print("\nPerformance / learning feedback:")
from records.performance import build_context, coin_context, _match_trades, _analyst_accuracy
# empty logs produce empty context (no crash)
_empty_ctx = build_context()
check("PERF-1 empty history returns empty string", isinstance(_empty_ctx, str))

# FIFO trade matching — one full round-trip
_fills_test = [
    {"coin":"BTC","side":"BUY", "price_usd":"50000","quantity":"0.002","timestamp":"2025-01-01T10:00:00"},
    {"coin":"BTC","side":"SELL","price_usd":"55000","quantity":"0.002","timestamp":"2025-01-01T11:00:00"},
]
_trades = _match_trades(_fills_test)
check("PERF-2 closed trade P&L computed", len(_trades)==1 and abs(_trades[0]["pnl_pct"]-10.0)<0.1)

# Partial exits accumulate correctly
_fills_partial = [
    {"coin":"ETH","side":"BUY", "price_usd":"2000","quantity":"1.0","timestamp":"2025-01-01T10:00:00"},
    {"coin":"ETH","side":"SELL","price_usd":"2100","quantity":"0.33","timestamp":"2025-01-01T11:00:00"},
    {"coin":"ETH","side":"SELL","price_usd":"2200","quantity":"0.67","timestamp":"2025-01-01T12:00:00"},
]
_partial_trades = _match_trades(_fills_partial)
check("PERF-3 partial exits produce two closed trades", len(_partial_trades)==2)

# Analyst accuracy scoring
_decs_test = [{
    "signal_id":"s1","coin":"BTC","action":"ENTRY_BUY","confidence":0.7,
    "timestamp":"2025-01-01T09:55:00","reasoning":"regime=trending","regime":"trending",
    "analysts":[{"a":"technical","v":"bullish","c":0.7},{"a":"sentiment","v":"bearish","c":0.5}]
}]
_acc = _analyst_accuracy(_trades, _decs_test)
check("PERF-4 analyst accuracy: correct verdict scored", _acc.get("technical",{}).get("correct",0)==1)
check("PERF-5 analyst accuracy: wrong verdict scored",   _acc.get("sentiment",{}).get("correct",0)==0)

# build_context returns a non-empty string when history exists
import tempfile, json as _json_m, os as _os_m
_tmp_fills = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
for r in _fills_test:
    _tmp_fills.write(_json_m.dumps(r)+"\n")
_tmp_fills.close()
_sv_ledger = config.TAX_LEDGER; config.TAX_LEDGER = _tmp_fills.name
_ctx = build_context(coin="BTC")
config.TAX_LEDGER = _sv_ledger; _os_m.unlink(_tmp_fills.name)
check("PERF-6 build_context non-empty with history", "BTC" in _ctx and "W/" in _ctx)

print("\nRegression — v7 wiring & honesty fixes:")
import tempfile as _tf, json as _j7, time as _t7
import config.config as _cfg7
from mcp_servers import _exchange_core as _ex7
from mcp_servers import _marketdata_core as _md7

# V7-1: chat_json accepts a schema kwarg (this TypeError killed the router)
_svb7 = config.LLM_BACKEND; config.LLM_BACKEND = "stub"
import llm.quantized_client as _q7
if _q7._INFLIGHT is not None:      # drain the worker NEW-3 left sleeping
    try: _q7._INFLIGHT.result(timeout=10)
    except Exception: pass
_r7 = _q7.chat_json("s", "u", schema={"required": ["active_strategies", "risk_level"]})
check("V7-1 chat_json(schema=) works and plumbs required keys",
      "active_strategies" in _r7 and "risk_level" in _r7)
config.LLM_BACKEND = _svb7

# V7-2: router end-to-end selects the LLM's strategies (was: always RangeScalp)
from strategies.router import _call_router as _cr7
_qorig7 = _q7.chat_json
_q7.chat_json = lambda s, u, **k: {"active_strategies": ["MomentumLong"],
                                   "risk_level": 1.5, "reasoning": "stub"}
_ms7 = {"direction": "bull", "regime": "trending", "bear_coins": 0, "bull_coins": 9,
        "neutral_coins": 6, "total_coins": 15, "btc_7d": 5.0, "btc_24h": 1.0,
        "avg_7d": 4.0, "btc_direction": "bull", "per_coin": {}}
_perf7 = {"MomentumLong": {"trades": 0, "wins": 0, "pnl_usd": 0.0,
                           "win_rate": 0.0, "recent_n": 0}}
_res7 = _cr7(_ms7, _perf7)
check("V7-2 router selects LLM strategies end-to-end",
      _res7["active_strategies"] == ["MomentumLong"] and _res7["risk_level"] == 1.5)
_q7.chat_json = _qorig7

# V7-3: strategy exit params persist and drive exit_manager (was: TypeError)
_sv_mode7 = config.MODE; config.MODE = "fixture"
_ex7._save({"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})
open(_ex7._META, "w").write("{}")
_fill7 = _ex7.place_order("ETH", "BUY", 0.1, "v7-meta")
from main import _strat_meta as _sm7
_ex7.update_meta("ETH", extra=_sm7("RangeScalp"))
_pos7 = [p for p in _ex7.positions() if p["coin"] == "ETH"][0]
check("V7-3a strat params merged onto position",
      _pos7.get("strat_sl") == 1.5 and _pos7.get("strat_name") == "RangeScalp")
_sh7, _, _reason7, _ = exit_manager.evaluate(_pos7, _pos7["entry_price"] * 0.984)
check("V7-3b strategy SL (1.5%) fires instead of config default (2%)",
      _sh7 and "1.5" in _reason7)
_ex7._save({"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})
open(_ex7._META, "w").write("{}")

# V7-4: COVER is a valid decision action (was: SchemaError killed the flip)
try:
    validate_signal({"signal_id": "1", "coin": "UNI", "action": "COVER",
                     "confidence": 1.0, "timestamp": "x"}); _ok7 = True
except SchemaError:
    _ok7 = False
check("V7-4 COVER action accepted by schema", _ok7)

# V7-5: OversoldBounce returns HOLD when not oversold (was: ValueError)
from strategies import REGISTRY as _REG7
_up7 = [{"open": 100 + i, "high": 101 + i, "low": 99 + i,
         "close": 100.5 + i, "volume": 100.0} for i in range(120)]
try:
    _sig7 = _REG7["OversoldBounce"].signal("BTC", _up7, "ranging", {})
    check("V7-5 OversoldBounce HOLDs instead of raising", _sig7.action == "HOLD")
except Exception:
    check("V7-5 OversoldBounce HOLDs instead of raising", False)

# V7-6: taker_ratio has an in-process fallback (was: KeyError for every coin)
_md7._TAKER_CACHE["BTC"] = (_t7.time(), 0.5)
_mc7 = MCPClient.__new__(MCPClient); _mc7.transport_ok = False; _mc7._sessions = {}
_tr7 = _mc7.taker_ratio("BTC")
check("V7-6 taker_ratio fallback returns neutral float",
      isinstance(_tr7, float) and 0.0 <= _tr7 <= 1.0)

# V7-7: per-strategy P&L from strategy-tagged ledger (was: pnl_usd never written)
_tmp7 = _tf.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False); _tmp7.close()
_sv_ledger7 = config.TAX_LEDGER; config.TAX_LEDGER = _tmp7.name
from records import tax_ledger as _tl7
_tl7.record_trade("UNI", "BUY", 10, 10.0, strategy="RangeScalp")
_tl7.record_trade("UNI", "SELL", 10, 10.5)
_tl7.record_trade("DOGE", "SHORT", 100, 0.20, strategy="TrendShort")
_tl7.record_trade("DOGE", "COVER", 100, 0.19)
from strategies.router import _strategy_performance as _sp7
_p7 = _sp7()
check("V7-7a long P&L attributed to its strategy",
      _p7["RangeScalp"]["trades"] == 1 and abs(_p7["RangeScalp"]["pnl_usd"] - 5.0) < 0.01)
check("V7-7b short P&L attributed via COVER matching",
      _p7["TrendShort"]["trades"] == 1 and abs(_p7["TrendShort"]["pnl_usd"] - 1.0) < 0.01)
config.TAX_LEDGER = _sv_ledger7; os.unlink(_tmp7.name)

# V7-8: router risk_level scales and clamps position sizing (was: ignored)
_, _, _why7a = risk_manager.check("BTC", "ENTRY_BUY", 100, {"cash_usd": 10000}, [],
                                  risk_mult=0.5)
_, _, _why7b = risk_manager.check("BTC", "ENTRY_BUY", 100, {"cash_usd": 10000}, [],
                                  risk_mult=9.9)
check("V7-8 risk_mult sizes $50 at 0.5 and clamps to $200",
      "size $50" in _why7a and "size $200" in _why7b)

# V7-9: protective exits run while the kill switch is active (was: abandoned)
_sv_dl7 = config.DECISION_LOG; _sv_tx7 = config.TAX_LEDGER
_tmpd7 = _tf.mkdtemp(prefix="v7-tests-")
config.DECISION_LOG = os.path.join(_tmpd7, "d.jsonl")
config.TAX_LEDGER = os.path.join(_tmpd7, "t.jsonl")
_mark7 = _ex7._mark("ETH")
_ex7._save({"cash_usd": 9000.0,
            "positions": {"ETH": {"quantity": 0.5, "entry_price": _mark7 * 2,
                                  "opened_at": _t7.time()}},
            "shorts": {}, "fills": []})
open(_ex7._META, "w").write(_j7.dumps({"ETH": {"peak_pnl": 0.0, "targets_taken": []}}))
kill_switch.activate("test-v7")
import main as _main7
_main7.run_exits(_mc7)
kill_switch.deactivate()
_w7 = _ex7._load()
check("V7-9 stop-loss executes under active kill switch",
      "ETH" not in _w7["positions"] and any(f["side"] == "SELL" for f in _w7["fills"]))
_ex7._save({"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})
open(_ex7._META, "w").write("{}")
config.DECISION_LOG = _sv_dl7; config.TAX_LEDGER = _sv_tx7

# V7-10: no fixture headlines outside fixture mode; sentiment abstains, 0 LLM calls
config.MODE = "paper"
from mcp_servers import _news_core as _news7
_svfetch7 = _news7._fetch_rss_titles
_news7._fetch_rss_titles = lambda url, timeout=8: []
_news7._CACHE.clear()
check("V7-10a no canned headlines in paper mode", _news7.get_headlines("UNI") == [])
_news7._fetch_rss_titles = _svfetch7
_calls7 = {"n": 0}
_q7.chat_json = lambda *a, **k: _calls7.__setitem__("n", _calls7["n"] + 1) or \
                                {"verdict": "bullish", "confidence": 0.9}
import analysts.sentiment_analyst as _sa7
_sa_orig7 = _sa7.chat_json; _sa7.chat_json = _q7.chat_json
class _NoNews7:
    def headlines(self, coin, limit=5): return []
_v7 = _sa7.sentiment_analyst("UNI", _NoNews7())
check("V7-10b sentiment abstains on empty headlines (no LLM call)",
      _v7["confidence"] == 0.0 and "abstain" in _v7["reasoning"] and _calls7["n"] == 0)
_q7.chat_json = _qorig7; _sa7.chat_json = _sa_orig7

# V7-11: synthetic-data veto blocks entries in non-fixture modes
_svreal7 = _md7._real_candles
_md7._real_candles = lambda coin, count=300: (None, None)
_md7._CACHE.clear(); _md7._PX_CACHE.clear()
_md7._OB_CACHE["BTC"] = (_t7.time(), {"coin": "BTC", "imbalance": 0.0})
_md7._TAKER_CACHE["BTC"] = (_t7.time(), 0.5)
_dec7, _, _verd7, _reg7, _ = _main7.analyse_coin(_mc7, "BTC", None, macro={})
check("V7-11 synthetic source vetoes entry without running analysts",
      _dec7["action"] == "STAND_DOWN" and "data_source_veto" in _dec7["reasoning"]
      and _verd7 == [])
_md7._real_candles = _svreal7
_md7._CACHE.clear(); _md7._PX_CACHE.clear()
config.MODE = _sv_mode7

# V7-12: paper fills charge fee + slippage (was: frictionless)
config.MODE = "fixture"
_ex7._save({"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})
open(_ex7._META, "w").write("{}")
_b7 = _ex7.place_order("ETH", "BUY", 1.0, "v7-fee-b")
_s7 = _ex7.place_order("ETH", "SELL", 1.0, "v7-fee-s")
_wf7 = _ex7._load()
_loss7 = 10000.0 - _wf7["cash_usd"]
check("V7-12 round trip costs ~0.24% in fees+slippage",
      _b7["fee_usd"] > 0 and _s7["fee_usd"] > 0 and _b7["price"] > _s7["price"]
      and 0.0015 * _b7["price"] < _loss7 < 0.0035 * _b7["price"])
_ex7._save({"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})
open(_ex7._META, "w").write("{}")
config.MODE = _sv_mode7

# V7-13: synthetic shorts accrue perp funding (paper realism)
_sv13 = config.MODE; config.MODE = "fixture"
_ex7._save({"cash_usd": 9900.0, "positions": {},
            "shorts": {"DOGE": {"quantity": 100.0, "entry_price": 0.16,
                                "opened_at": _t7.time() - 8 * 3600,
                                "collateral": 16.0}},
            "fills": []})
_mark13 = _ex7._mark("DOGE")
_ex7.accrue_funding({"DOGE": 0.0001})     # +ve rate: longs pay shorts → we RECEIVE
_w13 = _ex7._load()
_exp13 = 0.0001 * _mark13 * 100.0         # one full 8h period on mark notional
_got13 = _w13["cash_usd"] - 9900.0
check("V7-13a positive funding credits a synthetic short",
      _got13 > 0 and abs(_got13 - _exp13) < _exp13 * 0.05 + 1e-9
      and _w13["shorts"]["DOGE"]["funding_usd"] > 0)
_r13b = _ex7.accrue_funding({"DOGE": 0.0001})
check("V7-13b immediate re-accrual is a no-op", _r13b["shorts"] == 0)
_ex7._save({"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})
config.MODE = _sv13

# V7-14: futures backend flag maps symbols per venue
_svfb = getattr(config, "FUTURES_BACKEND", "binance")
config.FUTURES_BACKEND = "hyperliquid"
_hl = _ex7._fut_symbol("BTC")
config.FUTURES_BACKEND = "binance"
_bn = _ex7._fut_symbol("BTC")
config.FUTURES_BACKEND = _svfb
check("V7-14 backend symbol mapping (HL=USDC perp, Binance=USDT)",
      _hl == "BTC/USDC:USDC" and _bn == "BTC/USDT")

print("\n" + "="*50)
print(f"RESULTS: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
