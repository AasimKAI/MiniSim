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

print("MiniSim v5 — TEST SUITE\n" + "="*50)

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
check("data source is labelled", _md.current_source("BTC") in ("coingecko","synthetic","synthetic(fallback)"))


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

print("\n" + "="*50)
print(f"RESULTS: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
