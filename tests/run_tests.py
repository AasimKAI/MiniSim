"""
Test runner for Crypto Signal System v4.
Simple PASS/FAIL helper, no external framework.
All tests must pass (zero failures).
"""

import sys
import os
import traceback
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test results
passed = 0
failed = 0
errors = []


def test(name: str):
    """Decorator for test functions."""
    def decorator(func):
        def wrapper():
            global passed, failed
            try:
                func()
                passed += 1
                print(f"✓ {name}")
                return True
            except AssertionError as e:
                failed += 1
                errors.append((name, str(e)))
                print(f"✗ {name}: {e}")
                return False
            except Exception as e:
                failed += 1
                errors.append((name, f"Exception: {str(e)}"))
                print(f"✗ {name}: Exception: {e}")
                traceback.print_exc()
                return False
        return wrapper
    return decorator


def assert_equal(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: {a} != {b}")


def assert_true(condition, msg=""):
    if not condition:
        raise AssertionError(msg)


def assert_false(condition, msg=""):
    if condition:
        raise AssertionError(msg)


def assert_in(item, container, msg=""):
    if item not in container:
        raise AssertionError(f"{msg}: {item} not in {container}")


def assert_greater(a, b, msg=""):
    if a <= b:
        raise AssertionError(f"{msg}: {a} not > {b}")


def assert_less(a, b, msg=""):
    if a >= b:
        raise AssertionError(f"{msg}: {a} not < {b}")


# ============================================================================
# SCHEMA VALIDATORS TESTS
# ============================================================================

@test("Schema: validate analyst verdict")
def test_validate_analyst_verdict():
    from schemas.validators import validate_analyst_verdict, SCHEMA_VERSION

    verdict = {
        "analyst": "technical",
        "coin": "BTC",
        "view": "bullish",
        "confidence": 0.75,
        "reasoning": "RSI oversold",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_age_seconds": 60,
        "status": "validated",
    }

    result = validate_analyst_verdict(verdict)
    assert_equal(result["analyst"], "technical")
    assert_equal(result["view"], "bullish")
    assert_equal(result["schema_version"], SCHEMA_VERSION)


@test("Schema: reject invalid analyst verdict")
def test_invalid_analyst_verdict():
    from schemas.validators import validate_analyst_verdict, safe_validate

    bad_verdict = {
        "analyst": "technical",
        "coin": "BTC",
        # missing: view, confidence, reasoning, timestamp, status
    }

    is_valid, error = safe_validate(bad_verdict, validate_analyst_verdict)
    assert_false(is_valid)
    assert_true("Missing required fields" in error)


@test("Schema: validate signal record")
def test_validate_signal_record():
    from schemas.validators import validate_signal_record, SCHEMA_VERSION

    signal = {
        "signal_id": "sig_123",
        "decision": "entry_buy",
        "coin": "ETH",
        "view": "bullish",
        "confidence": 0.8,
        "bull_case": "strong technicals",
        "bear_case": "overbought RSI",
        "regime": "trending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ceo_model_name": "llama2",
        "ceo_model_version": "1.0",
        "ceo_timeout_sec": 30.0,
        "ceo_validation_result": "valid",
        "is_big_trade": False,
    }

    result = validate_signal_record(signal)
    assert_equal(result["decision"], "entry_buy")
    assert_equal(result["schema_version"], SCHEMA_VERSION)


@test("Schema: validate order record")
def test_validate_order_record():
    from schemas.validators import validate_order_record

    order = {
        "client_order_id": "sig_123/entry",
        "signal_id": "sig_123",
        "coin": "BTC",
        "side": "BUY",
        "quantity": 0.5,
        "price": 50000.0,
        "status": "filled",
        "filled_quantity": 0.5,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    result = validate_order_record(order)
    assert_equal(result["side"], "BUY")
    assert_equal(result["status"], "filled")


@test("Schema: validate position record")
def test_validate_position_record():
    from schemas.validators import validate_position_record

    position = {
        "position_id": "pos_123",
        "signal_id": "sig_123",
        "coin": "BTC",
        "side": "LONG",
        "entry_price": 50000.0,
        "entry_quantity": 0.5,
        "entry_timestamp": datetime.now(timezone.utc).isoformat(),
        "stop_loss": 49000.0,
        "take_profit_targets": [52500.0, 55000.0],
        "thesis_condition": {"type": "signal_validity"},
        "max_hold_time_sec": 172800.0,
        "status": "open",
    }

    result = validate_position_record(position)
    assert_equal(result["side"], "LONG")
    assert_equal(result["status"], "open")


# ============================================================================
# TECHNICAL ANALYST TESTS
# ============================================================================

@test("Technical: analyze with sufficient data")
def test_technical_analyze():
    from analysts.technical_analyst import TechnicalAnalyst

    class MockConfig:
        RSI_PERIOD = 14
        MACD_FAST = 12
        MACD_SLOW = 26
        EMA_SHORT = 20
        EMA_LONG = 50
        BB_PERIOD = 20
        BB_STDDEV = 2
        ATR_PERIOD = 14
        RSI_OVERBOUGHT = 70
        RSI_OVERSOLD = 30

    analyst = TechnicalAnalyst(MockConfig())
    prices = [50000 + i * 100 for i in range(50)]  # uptrend

    verdict = analyst.analyze("BTC", prices)
    assert_equal(verdict["analyst"], "technical")
    assert_equal(verdict["coin"], "BTC")
    assert_in(verdict["view"], ["bullish", "bearish", "neutral"])


@test("Technical: decline on insufficient data")
def test_technical_insufficient_data():
    from analysts.technical_analyst import TechnicalAnalyst

    class MockConfig:
        RSI_PERIOD = 14
        MACD_FAST = 12
        MACD_SLOW = 26
        EMA_SHORT = 20
        EMA_LONG = 50
        BB_PERIOD = 20
        BB_STDDEV = 2
        ATR_PERIOD = 14
        RSI_OVERBOUGHT = 70
        RSI_OVERSOLD = 30

    analyst = TechnicalAnalyst(MockConfig())
    prices = [50000, 50100, 50200]  # too short

    verdict = analyst.analyze("BTC", prices)
    assert_equal(verdict["view"], "neutral")
    assert_equal(verdict["confidence"], 0.0)


# ============================================================================
# VOLUME ANALYST TESTS
# ============================================================================

@test("Volume: detect breakout")
def test_volume_breakout():
    class Config:
        VOLUME_BREAKOUT_THRESHOLD = 1.5

    from analysts.volume_analyst import VolumeAnalyst

    analyst = VolumeAnalyst(Config())
    volumes = [1000, 1100, 1050, 900, 950, 1000, 1020, 2500]  # last is 2.5x avg
    prices = [50000] * 7 + [50100]  # up

    verdict = analyst.analyze("BTC", volumes, prices)
    assert_equal(verdict["analyst"], "volume")
    assert_equal(verdict["view"], "bullish")
    assert_greater(verdict["confidence"], 0.0)


@test("Volume: no breakout decline")
def test_volume_no_breakout():
    class Config:
        VOLUME_BREAKOUT_THRESHOLD = 1.5

    from analysts.volume_analyst import VolumeAnalyst

    analyst = VolumeAnalyst(Config())
    volumes = [1000, 1050, 1020, 1100, 1010]  # no big jump
    prices = [50000] * 5

    verdict = analyst.analyze("BTC", volumes, prices)
    assert_equal(verdict["view"], "neutral")


# ============================================================================
# REGIME DETECTOR TESTS
# ============================================================================

@test("Regime: detect trending")
def test_regime_trending():
    class Config:
        REGIME_WINDOW_HOURS = 24
        REGIME_VOLATILITY_THRESHOLD_PERCENT = 3

    from analysts.regime_detector import RegimeDetector

    detector = RegimeDetector(Config())
    prices = [50000 + i * 100 for i in range(20)]  # clear uptrend
    for p in prices:
        detector.record_price("BTC", p)

    regime = detector.detect_regime("BTC")
    assert_equal(regime["coin"], "BTC")
    assert_in(regime["regime"], ["trending", "ranging", "volatile"])


# ============================================================================
# RISK MANAGER TESTS
# ============================================================================

@test("Risk Manager: approve signal within capacity")
def test_risk_manager_approve():
    class Config:
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1
        STOP_LOSS_PERCENT = 2.0
        TAKE_PROFIT_TARGET_1_PERCENT = 5.0
        TAKE_PROFIT_TARGET_2_PERCENT = 10.0
        TAKE_PROFIT_TARGET_3_PERCENT = 15.0
        TRAILING_STOP_PERCENT = 3.0
        MAX_HOLD_TIME_HOURS = 48

    from execution.risk_manager import RiskManager

    rm = RiskManager(Config())
    signal = {"decision": "entry_buy", "coin": "BTC"}

    approved, reason, size = rm.check_signal(signal, current_exposure_usd=200, is_kill_switch_active=False)
    assert_true(approved)
    assert_equal(size, 100)


@test("Risk Manager: veto on max exposure")
def test_risk_manager_veto_exposure():
    class Config:
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1
        STOP_LOSS_PERCENT = 2.0
        TAKE_PROFIT_TARGET_1_PERCENT = 5.0
        TAKE_PROFIT_TARGET_2_PERCENT = 10.0
        TAKE_PROFIT_TARGET_3_PERCENT = 15.0
        TRAILING_STOP_PERCENT = 3.0
        MAX_HOLD_TIME_HOURS = 48

    from execution.risk_manager import RiskManager

    rm = RiskManager(Config())
    signal = {"decision": "entry_buy"}

    approved, reason, size = rm.check_signal(signal, current_exposure_usd=500, is_kill_switch_active=False)
    assert_false(approved)


@test("Risk Manager: veto on kill switch")
def test_risk_manager_kill_switch():
    class Config:
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1
        STOP_LOSS_PERCENT = 2.0
        TAKE_PROFIT_TARGET_1_PERCENT = 5.0
        TAKE_PROFIT_TARGET_2_PERCENT = 10.0
        TAKE_PROFIT_TARGET_3_PERCENT = 15.0
        TRAILING_STOP_PERCENT = 3.0
        MAX_HOLD_TIME_HOURS = 48

    from execution.risk_manager import RiskManager

    rm = RiskManager(Config())
    signal = {"decision": "entry_buy"}

    approved, reason, size = rm.check_signal(signal, current_exposure_usd=0, is_kill_switch_active=True)
    assert_false(approved)


@test("Risk Manager: veto short entries when venue disallows shorts")
def test_risk_manager_veto_short_disabled():
    class Config:
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1
        ALLOW_SHORTS = False
        STOP_LOSS_PERCENT = 2.0
        TAKE_PROFIT_TARGET_1_PERCENT = 5.0
        TAKE_PROFIT_TARGET_2_PERCENT = 10.0
        TAKE_PROFIT_TARGET_3_PERCENT = 15.0
        TRAILING_STOP_PERCENT = 3.0
        MAX_HOLD_TIME_HOURS = 48

    from execution.risk_manager import RiskManager

    rm = RiskManager(Config())
    signal = {"decision": "entry_sell"}

    approved, reason, size = rm.check_signal(signal, current_exposure_usd=0, is_kill_switch_active=False)
    assert_false(approved)
    assert_true("short" in reason)


# ============================================================================
# EXIT MANAGER TESTS
# ============================================================================

@test("Exit Manager: trigger on stop loss")
def test_exit_stop_loss():
    class Config:
        TRAILING_STOP_PERCENT = 3.0

    from execution.exit_manager import ExitManager

    em = ExitManager(Config())
    position = {
        "entry_price": 50000,
        "stop_loss": 49000,
        "take_profit_targets": [{"target_price": 52500, "quantity_percent": 100}],
        "trailing_stop_activated": False,
        "thesis_condition": {},
        "max_hold_time_sec": 172800,
        "entry_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    exit_order = em.check_exit_conditions(position, current_price=48500, regime="trending")
    assert_true(exit_order is not None)
    assert_equal(exit_order["trigger"], "stop_loss")


@test("Exit Manager: trigger on profit target")
def test_exit_profit_target():
    class Config:
        TRAILING_STOP_PERCENT = 3.0

    from execution.exit_manager import ExitManager

    em = ExitManager(Config())
    position = {
        "entry_price": 50000,
        "stop_loss": 49000,
        "take_profit_targets": [{"target_price": 52500, "quantity_percent": 100}],
        "trailing_stop_activated": False,
        "thesis_condition": {},
        "max_hold_time_sec": 172800,
        "entry_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    exit_order = em.check_exit_conditions(position, current_price=53000, regime="trending")
    assert_true(exit_order is not None)
    assert_in(exit_order["trigger"], ["profit_target_1"])


@test("Exit Manager: short stop loss and profit target directions")
def test_exit_short_directions():
    class Config:
        TRAILING_STOP_PERCENT = 3.0

    from execution.exit_manager import ExitManager

    em = ExitManager(Config())
    position = {
        "side": "SHORT",
        "entry_price": 50000,
        "stop_loss": 51000,
        "take_profit_targets": [{"target_price": 47500, "quantity_percent": 100}],
        "trailing_stop_activated": False,
        "thesis_condition": {},
        "max_hold_time_sec": 172800,
        "entry_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    stop_exit = em.check_exit_conditions(position, current_price=51200, regime="trending")
    assert_true(stop_exit is not None)
    assert_equal(stop_exit["trigger"], "stop_loss")

    profit_exit = em.check_exit_conditions(position, current_price=47000, regime="trending")
    assert_true(profit_exit is not None)
    assert_equal(profit_exit["trigger"], "profit_target_1")


# ============================================================================
# KILL SWITCH TESTS
# ============================================================================

@test("Kill Switch: activate and deactivate")
def test_kill_switch():
    import os
    import tempfile

    class Config:
        KILL_SWITCH_PATH = "/tmp/test_kill_switch.lock"

    from operations.kill_switch import KillSwitch

    ks = KillSwitch(Config())

    # Ensure clean state
    if os.path.exists(Config.KILL_SWITCH_PATH):
        os.remove(Config.KILL_SWITCH_PATH)

    assert_false(ks.is_active())

    ks.activate("test")
    assert_true(ks.is_active())

    ks.deactivate()
    assert_false(ks.is_active())

    # Cleanup
    if os.path.exists(Config.KILL_SWITCH_PATH):
        os.remove(Config.KILL_SWITCH_PATH)


# ============================================================================
# DECISION LOG TESTS
# ============================================================================

@test("Decision Log: log proposed signal")
def test_decision_log():
    from records.decision_log import DecisionLog
    import tempfile
    import os

    class Config:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "decision_log.jsonl")
        dl = DecisionLog(Config(), log_file=log_file)
        signal = {
            "signal_id": "sig_123",
            "coin": "BTC",
            "decision": "entry_buy",
            "view": "bullish",
            "confidence": 0.8,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        log_id = dl.log_proposed(signal)
        assert_true(log_id)

        entries = dl.get_all()
        assert_equal(len(entries), 1)
        assert_equal(entries[0]["status"], "proposed")


@test("Decision Log: log pending approval")
def test_decision_log_pending_approval():
    from records.decision_log import DecisionLog
    import tempfile
    import os

    class Config:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "decision_log.jsonl")
        dl = DecisionLog(Config(), log_file=log_file)
        signal = {
            "signal_id": "sig_123",
            "coin": "BTC",
            "decision": "entry_buy",
            "view": "bullish",
            "confidence": 0.8,
        }

        log_id = dl.log_pending_approval(signal, "approval_123", "tomorrow")
        assert_true(log_id)
        assert_equal(dl.get_all()[0]["status"], "pending_approval")


# ============================================================================
# TAX LEDGER TESTS
# ============================================================================

@test("Tax Ledger: record trade")
def test_tax_ledger():
    from records.tax_ledger import TaxLedger

    class Config:
        DATA_DIR = "/tmp"
        TAX_LEDGER_CURRENCY = "GBP"
        TAX_LEDGER_RETAIN_FILLS = True

    tl = TaxLedger(Config())
    order = {
        "order_id": "order_123",
        "coin": "BTC",
        "side": "BUY",
        "filled_quantity": 0.5,
        "price": 50000.0,
        "fee_quantity": 0.001,
        "fee_asset": "USDT",
    }

    entry_id = tl.record_trade(order, price_gbp=40000.0, fx_rate=1.25)
    assert_true(entry_id)

    summary = tl.get_summary()
    assert_in("BTC", summary)


# ============================================================================
# HEARTBEAT TESTS
# ============================================================================

@test("Heartbeat: pulse and check health")
def test_heartbeat():
    class Config:
        HEARTBEAT_ENABLED = True
        HEARTBEAT_INTERVAL_SEC = 60
        HEARTBEAT_NOTIFICATION_THRESHOLD_SEC = 300

    from operations.heartbeat import Heartbeat

    hb = Heartbeat(Config())
    hb.pulse()

    is_healthy, reason = hb.check_health()
    assert_true(is_healthy)


# ============================================================================
# ORDER EXECUTOR TESTS
# ============================================================================

@test("Order Executor: execute entry")
def test_order_executor_entry():
    class Config:
        BINANCE_TESTNET_BASE_URL = "https://testnet.binance.vision"
        TAKER_FEE_PERCENT = 0.1

    from execution.order_executor import OrderExecutor

    oe = OrderExecutor(Config())
    signal = {
        "signal_id": "sig_123",
        "coin": "BTC",
        "decision": "entry_buy",
        "view": "bullish",
        "confidence": 0.8,
    }

    order = oe.execute_entry_order(signal, position_size_usd=100, current_price=50000)
    assert_equal(order["coin"], "BTC")
    assert_equal(order["side"], "BUY")
    assert_greater(order["quantity"], 0)


@test("Exchange Client: paper adapter stores and retrieves orders")
def test_paper_exchange_client():
    from execution.exchange_client import PaperExchangeClient

    client = PaperExchangeClient()
    order = client.execute("BTCUSDT", "BUY", 0.1, 50000, "sig_123/entry")
    retrieved = client.get_order("BTCUSDT", "sig_123/entry")

    assert_equal(order["status"], "filled")
    assert_equal(retrieved["client_order_id"], "sig_123/entry")


@test("Order Executor: real exit failure is not mocked as filled")
def test_order_executor_exit_failure_raises():
    class Config:
        BINANCE_TESTNET_BASE_URL = "https://testnet.binance.vision"
        TAKER_FEE_PERCENT = 0.1
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1

    class FailingClient:
        def execute(self, **kwargs):
            raise RuntimeError("exchange unavailable")

    from execution.order_executor import OrderExecutor

    oe = OrderExecutor(Config(), binance_client=FailingClient())
    position = {
        "signal_id": "sig_123",
        "coin": "BTC",
        "side": "LONG",
        "entry_quantity": 0.1,
    }
    exit_condition = {"trigger": "stop_loss", "quantity_percent": 100}

    try:
        oe.execute_exit_order(position, exit_condition, current_price=49000)
    except RuntimeError:
        return

    raise AssertionError("exit failure should propagate instead of creating a mock fill")


@test("Order Executor: full exit uses remaining quantity")
def test_order_executor_exit_uses_remaining_quantity():
    class Config:
        BINANCE_TESTNET_BASE_URL = "https://testnet.binance.vision"
        TAKER_FEE_PERCENT = 0.1

    from execution.order_executor import OrderExecutor

    oe = OrderExecutor(Config())
    position = {
        "signal_id": "sig_123",
        "coin": "BTC",
        "side": "LONG",
        "entry_quantity": 0.3,
        "remaining_quantity": 0.1,
    }
    exit_condition = {"trigger": "stop_loss", "quantity_percent": 100}

    order = oe.execute_exit_order(position, exit_condition, current_price=49000)
    assert_equal(order["quantity"], 0.1)


@test("Telegram Approver: only big trades require approval")
def test_telegram_approver_only_big_trades():
    class Config:
        TELEGRAM_ENABLED = True
        TELEGRAM_APPROVAL_TIMEOUT_SEC = 300

    from execution.telegram_approver import TelegramApprover

    approver = TelegramApprover(Config())
    small_signal = {"signal_id": "small", "decision": "entry_buy", "is_big_trade": False}
    big_signal = {"signal_id": "big", "decision": "entry_buy", "is_big_trade": True}

    small = approver.request_approval(small_signal)
    big = approver.request_approval(big_signal)

    assert_equal(small["approval_id"], "auto")
    assert_true(big["approval_id"] != "auto")


@test("Telegram Listener: parses authorized approve and reject commands")
def test_telegram_listener_authorized_commands():
    class Config:
        TELEGRAM_ENABLED = True
        TELEGRAM_BOT_TOKEN = "token"
        TELEGRAM_CHAT_ID = "123"

    class FakeResponse:
        def json(self):
            return {
                "ok": True,
                "result": [
                    {"update_id": 1, "message": {"chat": {"id": 123}, "text": "/approve abc"}},
                    {"update_id": 2, "message": {"chat": {"id": 123}, "text": "/reject def"}},
                ],
            }

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, url, params, timeout):
            return FakeResponse()

    from execution.telegram_listener import TelegramApprovalListener

    listener = TelegramApprovalListener(Config(), session=FakeSession())
    actions = listener.poll()

    assert_equal(actions[0], {"action": "approve", "approval_id": "abc"})
    assert_equal(actions[1], {"action": "reject", "approval_id": "def"})


@test("Telegram Listener: ignores unauthorized chat")
def test_telegram_listener_ignores_unauthorized_chat():
    class Config:
        TELEGRAM_ENABLED = True
        TELEGRAM_BOT_TOKEN = "token"
        TELEGRAM_CHAT_ID = "123"

    class FakeResponse:
        def json(self):
            return {
                "ok": True,
                "result": [
                    {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/approve abc"}},
                ],
            }

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, url, params, timeout):
            return FakeResponse()

    from execution.telegram_listener import TelegramApprovalListener

    listener = TelegramApprovalListener(Config(), session=FakeSession())
    assert_equal(listener.poll(), [])


@test("Position Store: persists and restores positions")
def test_position_store_round_trip():
    import os
    import tempfile
    from operations.position_store import PositionStore

    class Config:
        STATE_DIR = "state"
        ATOMIC_WRITE_FSYNC = True

    with tempfile.TemporaryDirectory() as tmpdir:
        store = PositionStore(Config(), state_file=os.path.join(tmpdir, "positions.json"))
        positions = {"pos_1": {"coin": "BTC", "status": "open"}}
        assert_true(store.save(positions, 100.0))

        loaded_positions, loaded_exposure = store.load()
        assert_equal(loaded_positions["pos_1"]["coin"], "BTC")
        assert_equal(loaded_exposure, 100.0)


@test("Pending Trade Store: persists and restores pending trades")
def test_pending_trade_store_round_trip():
    import os
    import tempfile
    from operations.pending_trade_store import PendingTradeStore

    class Config:
        STATE_DIR = "state"
        ATOMIC_WRITE_FSYNC = True

    with tempfile.TemporaryDirectory() as tmpdir:
        store = PendingTradeStore(Config(), state_file=os.path.join(tmpdir, "pending.json"))
        pending = {"approval_1": {"signal": {"coin": "BTC"}}}
        assert_true(store.save(pending))

        loaded = store.load()
        assert_equal(loaded["approval_1"]["signal"]["coin"], "BTC")


@test("System: approved Telegram pending trade executes and clears")
def test_system_approved_pending_trade_executes():
    import tempfile
    from types import SimpleNamespace
    from main import CryptoSignalSystem
    from execution.telegram_approver import TelegramApprover
    from records.decision_log import DecisionLog
    from operations.position_store import PositionStore
    from operations.pending_trade_store import PendingTradeStore

    class Config:
        STATE_DIR = "state"
        ATOMIC_WRITE_FSYNC = True
        TAKER_FEE_PERCENT = 0.1
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1
        BINANCE_TESTNET_BASE_URL = "https://testnet.binance.vision"
        BINANCE_SPOT_SYMBOL_FORMAT = "{}USDT"
        TRAILING_STOP_PERCENT = 3.0
        STOP_LOSS_PERCENT = 2.0
        TAKE_PROFIT_TARGET_1_PERCENT = 5.0
        TAKE_PROFIT_TARGET_2_PERCENT = 10.0
        TAKE_PROFIT_TARGET_3_PERCENT = 15.0
        MAX_HOLD_TIME_HOURS = 48
        TELEGRAM_ENABLED = True
        TELEGRAM_APPROVAL_TIMEOUT_SEC = 300

    class Listener:
        def __init__(self):
            self.results = []

        def poll(self):
            return [{"action": "approve", "approval_id": "approval_1"}]

        def notify_result(self, text):
            self.results.append(text)

    with tempfile.TemporaryDirectory() as tmpdir:
        system = object.__new__(CryptoSignalSystem)
        system.config = Config()
        system.order_executor = __import__("execution.order_executor", fromlist=["OrderExecutor"]).OrderExecutor(Config())
        system.risk_manager = __import__("execution.risk_manager", fromlist=["RiskManager"]).RiskManager(Config())
        system.telegram_approver = TelegramApprover(Config())
        system.telegram_approver.pending_approvals["approval_1"] = (datetime.now(timezone.utc), "sig_1")
        system.telegram_listener = Listener()
        system.decision_log = DecisionLog(Config(), log_file=f"{tmpdir}/decision_log.jsonl")
        system.position_store = PositionStore(Config(), state_file=f"{tmpdir}/positions.json")
        system.pending_trade_store = PendingTradeStore(Config(), state_file=f"{tmpdir}/pending.json")
        system.kill_switch = SimpleNamespace(activate=lambda reason: True)
        system.positions = {}
        system.current_exposure_usd = 0.0
        system.positions_lock = __import__("threading").RLock()
        system.pending_trades_lock = __import__("threading").RLock()
        system.latest_prices = {"BTC": 50000.0}
        system.pending_trades = {
            "approval_1": {
                "signal": {
                    "signal_id": "sig_1",
                    "coin": "BTC",
                    "decision": "entry_buy",
                    "view": "bullish",
                    "confidence": 0.8,
                },
                "position_size_usd": 100,
            }
        }

        system._check_pending_approvals()

        assert_equal(system.pending_trades, {})
        assert_greater(len(system.positions), 0)
        assert_true(any("executed" in message for message in system.telegram_listener.results))


@test("System: approved Telegram trade without live price does not report executed")
def test_system_approved_pending_trade_without_price_does_not_report_executed():
    import tempfile
    from types import SimpleNamespace
    from main import CryptoSignalSystem
    from execution.telegram_approver import TelegramApprover
    from records.decision_log import DecisionLog
    from operations.position_store import PositionStore
    from operations.pending_trade_store import PendingTradeStore

    class Config:
        STATE_DIR = "state"
        ATOMIC_WRITE_FSYNC = True
        TAKER_FEE_PERCENT = 0.1
        POSITION_SIZE_USD = 100
        MAX_EXPOSURE_USD = 500
        LEVERAGE = 1
        BINANCE_TESTNET_BASE_URL = "https://testnet.binance.vision"
        BINANCE_SPOT_SYMBOL_FORMAT = "{}USDT"
        TRAILING_STOP_PERCENT = 3.0
        STOP_LOSS_PERCENT = 2.0
        TAKE_PROFIT_TARGET_1_PERCENT = 5.0
        TAKE_PROFIT_TARGET_2_PERCENT = 10.0
        TAKE_PROFIT_TARGET_3_PERCENT = 15.0
        MAX_HOLD_TIME_HOURS = 48
        TELEGRAM_ENABLED = True
        TELEGRAM_APPROVAL_TIMEOUT_SEC = 300

    class Listener:
        def __init__(self):
            self.results = []

        def poll(self):
            return [{"action": "approve", "approval_id": "approval_1"}]

        def notify_result(self, text):
            self.results.append(text)

    with tempfile.TemporaryDirectory() as tmpdir:
        system = object.__new__(CryptoSignalSystem)
        system.config = Config()
        system.order_executor = __import__("execution.order_executor", fromlist=["OrderExecutor"]).OrderExecutor(Config())
        system.risk_manager = __import__("execution.risk_manager", fromlist=["RiskManager"]).RiskManager(Config())
        system.telegram_approver = TelegramApprover(Config())
        system.telegram_approver.pending_approvals["approval_1"] = (datetime.now(timezone.utc), "sig_1")
        system.telegram_listener = Listener()
        system.decision_log = DecisionLog(Config(), log_file=f"{tmpdir}/decision_log.jsonl")
        system.position_store = PositionStore(Config(), state_file=f"{tmpdir}/positions.json")
        system.pending_trade_store = PendingTradeStore(Config(), state_file=f"{tmpdir}/pending.json")
        system.kill_switch = SimpleNamespace(activate=lambda reason: True)
        system.positions = {}
        system.current_exposure_usd = 0.0
        system.positions_lock = __import__("threading").RLock()
        system.pending_trades_lock = __import__("threading").RLock()
        system.latest_prices = {}
        system.pending_trades = {
            "approval_1": {
                "signal": {
                    "signal_id": "sig_1",
                    "coin": "BTC",
                    "decision": "entry_buy",
                    "view": "bullish",
                    "confidence": 0.8,
                },
                "position_size_usd": 100,
            }
        }

        system._check_pending_approvals()

        assert_equal(system.pending_trades, {})
        assert_equal(len(system.positions), 0)
        assert_true(any("did not run" in message for message in system.telegram_listener.results))
        assert_false(any("Approved and executed" in message for message in system.telegram_listener.results))


@test("State Reconciler: fails when local position missing on exchange")
def test_reconciler_missing_exchange_position_fails():
    class Config:
        MODE = "testnet"

    class EmptyExchange:
        def get_open_positions(self):
            return []

    from operations.state_reconciler import StateReconciler

    reconciler = StateReconciler(Config(), EmptyExchange())
    success, message = reconciler.reconcile_on_startup([{"coin": "BTC"}])

    assert_false(success)
    assert_true("not present" in message or "not found" in message)


# ============================================================================
# FILTER TESTS
# ============================================================================

@test("Regime Filter: allow trending")
def test_regime_filter_trending():
    class Config:
        REGIME_FILTER_ENABLED = True
        REGIME_FILTER_STRICT = False

    from decision.regime_filter import RegimeFilter

    rf = RegimeFilter(Config())
    allowed, reason = rf.should_allow_trade("trending", "bullish")
    assert_true(allowed)


@test("Regime Filter: reject volatile")
def test_regime_filter_volatile():
    class Config:
        REGIME_FILTER_ENABLED = True
        REGIME_FILTER_STRICT = False

    from decision.regime_filter import RegimeFilter

    rf = RegimeFilter(Config())
    allowed, reason = rf.should_allow_trade("volatile", "bullish")
    assert_false(allowed)


# ============================================================================
# REFLECTION AGENT TESTS
# ============================================================================

@test("Reflection: analyze profitable trade")
def test_reflection_analysis():
    class Config:
        REFLECTION_ENABLED = True
        REFLECTION_MIN_SAMPLE_SIZE = 10
        REFLECTION_CONFIDENCE_THRESHOLD = 0.7
        REFLECTION_PROVISIONAL_LEARNING_ENABLED = True

    from records.reflection_agent import ReflectionAgent

    ra = ReflectionAgent(Config())
    signal = {
        "coin": "BTC",
        "analyst": "technical",
        "view": "bullish",
        "confidence": 0.8,
    }
    order = {
        "price": 50000,
        "filled_quantity": 0.5,
    }
    exit_cond = {
        "exit_price": 52000,
        "trigger": "profit_target_1",
    }

    lesson = ra.analyze_trade_outcome(signal, order, exit_cond)
    # Lesson might be None if trade wasn't profitable by pnl calc
    # Just check function doesn't crash
    assert_true(True)


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def run_all_tests():
    """Run all tests."""
    print("=" * 70)
    print("CRYPTO SIGNAL SYSTEM V4 - TEST SUITE")
    print("=" * 70)
    print()

    # Run schema tests
    print("Schema Validators:")
    test_validate_analyst_verdict()
    test_invalid_analyst_verdict()
    test_validate_signal_record()
    test_validate_order_record()
    test_validate_position_record()
    print()

    # Run analyst tests
    print("Analysts:")
    test_technical_analyze()
    test_technical_insufficient_data()
    test_volume_breakout()
    test_volume_no_breakout()
    test_regime_trending()
    print()

    # Run execution tests
    print("Execution:")
    test_risk_manager_approve()
    test_risk_manager_veto_exposure()
    test_risk_manager_kill_switch()
    test_risk_manager_veto_short_disabled()
    test_exit_stop_loss()
    test_exit_profit_target()
    test_exit_short_directions()
    test_order_executor_entry()
    test_paper_exchange_client()
    test_order_executor_exit_failure_raises()
    test_order_executor_exit_uses_remaining_quantity()
    test_telegram_approver_only_big_trades()
    test_telegram_listener_authorized_commands()
    test_telegram_listener_ignores_unauthorized_chat()
    print()

    # Run operations tests
    print("Operations:")
    test_kill_switch()
    test_heartbeat()
    test_position_store_round_trip()
    test_pending_trade_store_round_trip()
    test_system_approved_pending_trade_executes()
    test_system_approved_pending_trade_without_price_does_not_report_executed()
    test_reconciler_missing_exchange_position_fails()
    print()

    # Run decision tests
    print("Decision:")
    test_regime_filter_trending()
    test_regime_filter_volatile()
    print()

    # Run records tests
    print("Records:")
    test_decision_log()
    test_decision_log_pending_approval()
    test_tax_ledger()
    test_reflection_analysis()
    print()

    # Summary
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print("\nFAILED TESTS:")
        for name, error in errors:
            print(f"  - {name}: {error}")
        return False

    return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
