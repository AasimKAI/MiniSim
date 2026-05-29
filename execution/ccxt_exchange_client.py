"""
CCXT-based exchange client for multi-exchange support.
Same interface as PaperExchangeClient and BinanceSpotTestnetClient.
Supports 100+ exchanges.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CCXTExchangeClient:
    """Exchange adapter backed by the CCXT library."""

    def __init__(self, config):
        try:
            import ccxt
        except ImportError:
            raise ImportError("ccxt is required. Install with: pip install ccxt")

        self.config = config
        exchange_id = getattr(config, "CCXT_EXCHANGE", "binance")
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Unknown CCXT exchange: {exchange_id}")

        exchange_cls = getattr(ccxt, exchange_id)
        self.exchange = exchange_cls(
            {
                "apiKey": getattr(config, "CCXT_API_KEY", None),
                "secret": getattr(config, "CCXT_API_SECRET", None),
                "enableRateLimit": True,
                "sandbox": getattr(config, "CCXT_SANDBOX", False),
            }
        )
        logger.info(f"CCXTExchangeClient initialized: {exchange_id}")

    # ------------------------------------------------------------------
    # Core interface (matches PaperExchangeClient / BinanceSpotTestnetClient)
    # ------------------------------------------------------------------

    def execute(self, symbol: str, side: str, quantity: float, price: float, client_order_id: str) -> Dict:
        """Execute a market order."""
        try:
            order = self.exchange.create_market_order(
                symbol=symbol,
                side=side.lower(),
                amount=quantity,
                params={"clientOrderId": client_order_id},
            )
            return self._normalize(order, fallback_price=price)
        except Exception as e:
            logger.error(f"CCXT execute error [{symbol} {side}]: {e}")
            raise

    def get_order(self, symbol: str, client_order_id: str) -> Dict:
        """Fetch order by client order ID."""
        try:
            orders = self.exchange.fetch_orders(symbol)
            for o in orders:
                if o.get("clientOrderId") == client_order_id:
                    return self._normalize(o)
            raise ValueError(f"Order not found: {client_order_id}")
        except Exception as e:
            logger.error(f"CCXT get_order error: {e}")
            raise

    def get_open_positions(self) -> List[Dict]:
        """Return non-zero asset balances as position records."""
        try:
            balance = self.exchange.fetch_balance()
            positions = []
            for asset, amounts in balance.items():
                if asset in ("info", "free", "used", "total"):
                    continue
                if not isinstance(amounts, dict):
                    continue
                total = float(amounts.get("total") or 0)
                quote = getattr(self.config, "CCXT_QUOTE_CURRENCY", "USDT")
                if asset != quote and total > 0:
                    positions.append(
                        {"coin": asset, "side": "LONG", "exchange_quantity": total}
                    )
            return positions
        except Exception as e:
            logger.error(f"CCXT get_open_positions error: {e}")
            return []

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[List]:
        """
        Fetch OHLCV bars. Returns list of [timestamp_ms, open, high, low, close, volume].
        Used by the backtest OHLC fetcher.
        """
        params = {}
        if limit:
            params["limit"] = limit
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, params=params)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize(self, order: Dict, fallback_price: Optional[float] = None) -> Dict:
        filled = float(order.get("filled") or 0)
        avg_price = float(order.get("average") or 0) or (fallback_price or 0)
        fee = order.get("fee") or {}
        status_map = {
            "open": "pending",
            "closed": "filled",
            "canceled": "cancelled",
            "rejected": "failed",
            "expired": "failed",
        }
        return {
            "order_id": str(order.get("id", "")),
            "client_order_id": order.get("clientOrderId", ""),
            "status": status_map.get(str(order.get("status", "")).lower(), "pending"),
            "filled_quantity": filled,
            "filled_price": avg_price,
            "fee_asset": fee.get("currency", "USDT"),
            "fee_quantity": float(fee.get("cost") or 0),
        }
