#!/usr/bin/env python3
"""
CRYPTO SIGNAL SYSTEM V2 - MAIN ENTRY POINT
Orchestrates 6 layers: Data, Analysis, Decision, Execution, Operations, Records.
Supports modes: fixture, historical_replay, paper, testnet.
"""

import logging
import time
import signal
import sys
from datetime import datetime, timezone

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CryptoSignalSystem:
    """Main system orchestrator."""

    def __init__(self, config_module='config.config', secrets_module='config.secrets'):
        """Initialize system with config."""
        try:
            self.config = self._load_module(config_module)
            self.secrets = self._load_module(secrets_module)
        except ImportError:
            logger.error(f"Failed to import config/secrets. Ensure config.py and secrets.py exist.")
            raise

        self.mode = self.config.MODE
        logger.info(f"CryptoSignalSystem v2 initializing in mode: {self.mode}")

        # Initialize all components
        self._init_layers()
        self.running = False

    def _load_module(self, module_name):
        """Dynamically load module."""
        import importlib
        return importlib.import_module(module_name)

    def _init_layers(self):
        """Initialize all 6 layers."""
        logger.info("Initializing layers...")

        # Layer A: Data & Edge Validation
        from collector.collector import Collector
        from collector.filter import DataFilter
        self.collector = Collector(self.config)
        self.filter = DataFilter(self.config)

        # Layer B: Analysis & Regime Detection
        from analysts.technical_analyst import TechnicalAnalyst
        from analysts.volume_analyst import VolumeAnalyst
        from analysts.order_book_analyst import OrderBookAnalyst
        from analysts.on_chain_analyst import OnChainAnalyst
        from analysts.sentiment_analyst import SentimentAnalyst
        from analysts.regime_detector import RegimeDetector

        self.analysts = {
            "technical": TechnicalAnalyst(self.config),
            "volume": VolumeAnalyst(self.config),
            "order_book": OrderBookAnalyst(self.config),
            "on_chain": OnChainAnalyst(self.config),
            "sentiment": SentimentAnalyst(self.config),
        }
        self.regime_detector = RegimeDetector(self.config)

        # Layer C: Decision
        from decision.regime_filter import RegimeFilter
        from decision.researcher import BullResearcher, BearResearcher
        from decision.ceo_agent import CEOAgent

        self.regime_filter = RegimeFilter(self.config)
        self.bull_researcher = BullResearcher(self.config)
        self.bear_researcher = BearResearcher(self.config)
        self.ceo_agent = CEOAgent(self.config)

        # Layer D: Execution & Exit Management
        from execution.risk_manager import RiskManager
        from execution.exit_manager import ExitManager
        from execution.order_executor import OrderExecutor
        from execution.telegram_approver import TelegramApprover

        self.risk_manager = RiskManager(self.config)
        self.exit_manager = ExitManager(self.config)
        self.order_executor = OrderExecutor(self.config)
        self.telegram_approver = TelegramApprover(self.config)

        # Layer E: Operations & Resilience
        from operations.watchdog import Watchdog
        from operations.state_reconciler import StateReconciler
        from operations.heartbeat import Heartbeat
        from operations.kill_switch import KillSwitch

        self.watchdog = Watchdog(self.config)
        self.state_reconciler = StateReconciler(self.config)
        self.heartbeat = Heartbeat(self.config)
        self.kill_switch = KillSwitch(self.config)

        # Layer F: Records & Guarded Learning
        from records.decision_log import DecisionLog
        from records.tax_ledger import TaxLedger
        from records.reflection_agent import ReflectionAgent

        self.decision_log = DecisionLog(self.config)
        self.tax_ledger = TaxLedger(self.config)
        self.reflection_agent = ReflectionAgent(self.config)

        # State
        self.positions = {}  # position_id -> position
        self.current_exposure_usd = 0.0

        logger.info("All layers initialized successfully")

    def start(self):
        """Start system."""
        logger.info(f"Starting Crypto Signal System v2 in {self.mode} mode...")

        if self.mode not in ["fixture", "historical_replay", "paper", "testnet"]:
            logger.error(f"Invalid mode: {self.mode}. Use: fixture, historical_replay, paper, testnet")
            return False

        # Check kill switch
        if self.kill_switch.is_active():
            logger.warning(f"Kill switch active: {self.kill_switch.get_reason()}")
            logger.warning("System halted. Deactivate kill switch to resume.")
            return False

        # Reconcile state on startup
        if self.config.STATE_RECONCILIATION_ON_STARTUP:
            success, msg = self.state_reconciler.reconcile_on_startup(list(self.positions.values()))
            if not success:
                logger.error(f"Reconciliation failed: {msg}")
                logger.warning("Standing down until reconciliation succeeds")
                return False

        self.running = True
        logger.info("System started. Running analysis/exit loops...")

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self._run_loops()
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            self.kill_switch.activate(f"fatal error: {str(e)[:100]}")
            return False
        finally:
            self.running = False

        return True

    def _run_loops(self):
        """Run main loops: 5-min analysis, 30-60s volume, continuous exit watch."""
        last_collection = 0
        last_volume_scan = 0
        last_exit_check = 0

        while self.running:
            now = time.time()

            # Exit watch loop (priority, runs every iteration)
            if now - last_exit_check > self.config.EXIT_WATCH_INTERVAL:
                self._check_exits()
                last_exit_check = now

            # 5-min collection & analysis loop
            if now - last_collection > self.config.COLLECTOR_INTERVAL:
                self._run_analysis_cycle()
                last_collection = now

            # Volume scan loop
            if now - last_volume_scan > self.config.VOLUME_SCAN_INTERVAL:
                self._run_volume_scan()
                last_volume_scan = now

            # Heartbeat
            self.heartbeat.pulse()

            # Small sleep to prevent busy loop
            time.sleep(1)

    def _run_analysis_cycle(self):
        """Execute full analysis cycle: collect, filter, analyze, decide."""
        logger.info("=" * 70)
        logger.info("Analysis Cycle Start")
        logger.info("=" * 70)

        # Layer A: Collect
        raw_data = self.collector.collect_all()
        if not raw_data:
            logger.error("Collection failed")
            return

        # Layer A: Filter
        clean_data = self.filter.filter_and_clean(raw_data)
        if not clean_data:
            logger.error("Filtering failed")
            return

        # Analyze each tracked coin
        for coin in self.config.TRACKED_COINS:
            self._analyze_coin(coin, clean_data)

        logger.info("Analysis Cycle Complete")

    def _analyze_coin(self, coin: str, clean_data: dict):
        """Analyze single coin."""
        logger.info(f"\n>>> Analyzing {coin}...")

        # Layer B: Get analysts verdicts
        verdicts = []
        for analyst_name, analyst in self.analysts.items():
            if not self.config.ANALYSTS_ENABLED.get(analyst_name, True):
                continue

            # Get analyst-specific data from clean_data
            # For now, use mock data
            if analyst_name == "technical":
                prices = [50000 + i * 100 for i in range(50)]
                verdict = analyst.analyze(coin, prices)
            elif analyst_name == "volume":
                volumes = [1000 * (1 + i * 0.05) for i in range(20)]
                prices = [50000 + i * 50 for i in range(20)]
                verdict = analyst.analyze(coin, volumes, prices)
            elif analyst_name == "order_book":
                verdict = analyst.analyze(coin, bid_volume=100, ask_volume=90, spread_percent=0.05)
            elif analyst_name == "on_chain":
                verdict = analyst.analyze(coin, transaction_volume=1000, active_addresses=150000, whale_activity=0.5)
            elif analyst_name == "sentiment":
                verdict = analyst.analyze(coin, news_sentiment="positive", reddit_sentiment="neutral", twitter_sentiment="positive")
            else:
                continue

            verdicts.append(verdict)
            logger.info(f"  {analyst_name}: {verdict.get('view')} ({verdict.get('confidence', 0):.1%})")

        # Layer B: Regime detection
        self.regime_detector.record_price(coin, 50000)  # mock current price
        regime_info = self.regime_detector.detect_regime(coin)
        regime = regime_info.get('regime', 'neutral')
        logger.info(f"  Regime: {regime}")

        # Layer C: Decision
        # Regime filter
        allowed, reason = self.regime_filter.should_allow_trade(regime, "bullish")
        if not allowed:
            logger.info(f"  Regime filter: {reason} (stand down)")
            return

        # Research
        bull_case = self.bull_researcher.build_case(coin, verdicts, regime)
        bear_case = self.bear_researcher.build_case(coin, verdicts, regime)

        # CEO decision
        signal = self.ceo_agent.decide(coin, bull_case, bear_case, regime, self.config.POSITION_SIZE_USD)

        if signal.get('decision') == 'stand_down':
            logger.info(f"  Decision: STAND DOWN ({signal.get('ceo_validation_result', '')})")
            return

        logger.info(f"  Decision: {signal.get('decision').upper()}")
        self.decision_log.log_proposed(signal)

        # Layer D: Risk management
        approved, rm_reason, position_size = self.risk_manager.check_signal(
            signal, self.current_exposure_usd, self.kill_switch.is_active()
        )

        if not approved:
            logger.info(f"  Risk Manager: VETO ({rm_reason})")
            self.decision_log.log_vetoed(signal, f"Risk veto: {rm_reason}")
            return

        # Telegram approval for big trades
        approval = self.telegram_approver.request_approval(signal)
        approval_id = approval.get('approval_id', 'auto')

        # Layer D: Execution
        current_price = 50000  # mock
        order = self.order_executor.execute_entry_order(signal, position_size, current_price)

        logger.info(f"  Order: {order.get('side')} {order.get('quantity'):.4f} {coin} @ {order.get('price'):.2f}")

        self.decision_log.log_approved(signal, approval_id)
        self.decision_log.log_executed(signal, order.get('order_id', ''), order.get('filled_price', 0))

        # Create position record
        position = {
            "position_id": f"pos_{signal.get('signal_id')}",
            "signal_id": signal.get('signal_id'),
            "coin": coin,
            "side": "LONG" if signal.get('decision') == 'entry_buy' else "SHORT",
            "entry_price": current_price,
            "entry_quantity": order.get('filled_quantity', 0),
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "stop_loss": current_price * 0.98,
            "take_profit_targets": [current_price * 1.05, current_price * 1.10],
            "trailing_stop_activated": False,
            "thesis_condition": {"type": "signal_validity"},
            "max_hold_time_sec": self.config.MAX_HOLD_TIME_HOURS * 3600,
            "status": "open",
        }

        self.positions[position.get('position_id')] = position
        self.current_exposure_usd += position_size

        logger.info(f"  Position opened: {position.get('position_id')}")

    def _run_volume_scan(self):
        """Run volume scan (separate, faster loop)."""
        logger.debug("Volume scan running...")
        # Implement separate volume scanning if needed

    def _check_exits(self):
        """Check exit conditions for all open positions (priority loop)."""
        current_price = 50000  # mock

        for position_id, position in list(self.positions.items()):
            exit_order = self.exit_manager.check_exit_conditions(
                position, current_price, "trending"  # mock regime
            )

            if exit_order:
                logger.info(f"Exit triggered for {position_id}: {exit_order.get('trigger')}")

                # Execute exit
                exit_exec = self.order_executor.execute_exit_order(position, exit_order, current_price)
                logger.info(f"Exit executed: {exit_exec.get('order_id')}")

                # Update position
                position['status'] = 'closed'
                self.decision_log.log_exited(
                    {"signal_id": position.get('signal_id'), "coin": position.get('coin')},
                    exit_order.get('trigger', 'unknown'),
                    exit_order.get('exit_price', 0)
                )

                # Record for tax
                self.tax_ledger.record_trade(exit_exec, price_gbp=40000, fx_rate=1.25)

                # Update exposure
                self.current_exposure_usd -= position.get('entry_quantity', 0) * position.get('entry_price', 0) * 0.01

    def _signal_handler(self, signum, frame):
        """Handle interrupt signals."""
        logger.warning(f"Signal {signum} received, shutting down gracefully...")
        self.running = False

    def stop(self):
        """Stop system."""
        logger.info("Stopping Crypto Signal System v2...")
        self.running = False


def main():
    """Main entry point."""
    try:
        system = CryptoSignalSystem()
        system.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
