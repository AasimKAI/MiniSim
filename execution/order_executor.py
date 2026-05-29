"""
LAYER D - ORDER EXECUTOR
Binance Testnet execution. Idempotent client order IDs.
Retries check exchange state. Records order IDs, fills, fees.
"""

import logging
import uuid
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class OrderExecutor:
    """Executes orders on Binance Testnet."""

    def __init__(self, config, binance_client=None):
        self.config = config
        self.binance_client = binance_client  # mock or real client
        self.testnet_base_url = config.BINANCE_TESTNET_BASE_URL

    def execute_entry_order(self, signal: Dict, position_size_usd: float, current_price: float) -> Dict:
        """
        Execute entry order for signal.
        Returns order record with exchange order ID.
        """
        coin = signal.get('coin', '')
        decision = signal.get('decision', '')

        if decision == 'entry_buy':
            side = 'BUY'
        elif decision == 'entry_sell':
            side = 'SELL'
        else:
            raise ValueError(f"Invalid decision: {decision}")

        # Calculate quantity
        quantity = position_size_usd / current_price if current_price > 0 else 0

        # Create idempotent client order ID
        signal_id = signal.get('signal_id', str(uuid.uuid4()))
        client_order_id = f"{signal_id}/entry"

        # Execute on exchange (mock or real)
        if self.binance_client:
            try:
                exchange_order = self.binance_client.execute(
                    symbol=f"{coin}USDT",
                    side=side,
                    quantity=quantity,
                    price=current_price,
                    client_order_id=client_order_id,
                )
            except Exception as e:
                error_msg = str(e).lower()
                # Check if this is a duplicate order ID error (idempotent - return existing order)
                if "duplicate" in error_msg or "client_order_id" in error_msg:
                    logger.warning(f"Duplicate client_order_id {client_order_id}: {e}")
                    # Try to fetch existing order from exchange
                    try:
                        exchange_order = self.binance_client.get_order(
                            symbol=f"{coin}USDT",
                            client_order_id=client_order_id,
                        )
                        logger.info(f"Retrieved existing order: {exchange_order}")
                    except Exception as fetch_err:
                        logger.error(f"Could not retrieve duplicate order: {fetch_err}")
                        raise ValueError(f"Duplicate order but cannot retrieve: {e}")
                else:
                    logger.error(f"Order execution failed: {e}")
                    raise
        else:
            # Mock for testing
            exchange_order = self._create_mock_order(signal_id, side, quantity, current_price)

        # Record order
        order_record = {
            "order_id": exchange_order.get('order_id', str(uuid.uuid4())),
            "client_order_id": client_order_id,
            "signal_id": signal_id,
            "coin": coin,
            "side": side,
            "quantity": quantity,
            "price": current_price,
            "status": exchange_order.get('status', 'filled'),
            "filled_quantity": exchange_order.get('filled_quantity', quantity),
            "filled_price": exchange_order.get('filled_price', current_price),
            "fee_asset": "USDT",
            "fee_quantity": quantity * current_price * (self.config.TAKER_FEE_PERCENT / 100),
            "timestamp": self._now_iso(),
            "exchange_timestamp": self._now_iso(),
            "schema_version": "1.0.0",
        }

        return order_record

    def execute_exit_order(self, position: Dict, exit_condition: Dict, current_price: float) -> Dict:
        """
        Execute exit order for position.
        Returns order record.
        """
        coin = position.get('coin', '')
        entry_side = position.get('side', 'LONG')
        exit_side = 'SELL' if entry_side == 'LONG' else 'BUY'
        quantity = position.get('entry_quantity', 0) * (exit_condition.get('quantity_percent', 100) / 100)

        signal_id = position.get('signal_id', str(uuid.uuid4()))
        client_order_id = f"{signal_id}/exit/{exit_condition.get('trigger', 'unknown')}"

        # Execute
        if self.binance_client:
            try:
                exchange_order = self.binance_client.execute(
                    symbol=f"{coin}USDT",
                    side=exit_side,
                    quantity=quantity,
                    price=current_price,
                    client_order_id=client_order_id,
                )
            except Exception as e:
                logger.error(f"Exit order failed: {e}")
                raise
        else:
            exchange_order = self._create_mock_order(signal_id, exit_side, quantity, current_price)

        order_record = {
            "order_id": exchange_order.get('order_id', str(uuid.uuid4())),
            "client_order_id": client_order_id,
            "signal_id": signal_id,
            "coin": coin,
            "side": exit_side,
            "quantity": quantity,
            "price": current_price,
            "status": exchange_order.get('status', 'filled'),
            "filled_quantity": exchange_order.get('filled_quantity', quantity),
            "filled_price": exchange_order.get('filled_price', current_price),
            "fee_asset": "USDT",
            "fee_quantity": quantity * current_price * (self.config.TAKER_FEE_PERCENT / 100),
            "timestamp": self._now_iso(),
            "exchange_timestamp": self._now_iso(),
            "schema_version": "1.0.0",
        }

        return order_record

    def _create_mock_order(self, signal_id: str, side: str, quantity: float, price: float) -> Dict:
        """Create mock order for testing/simulation."""
        return {
            "order_id": f"mock_{signal_id}",
            "status": "filled",
            "filled_quantity": quantity,
            "filled_price": price,
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
