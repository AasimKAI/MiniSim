"""
Exchange adapters for paper and Binance Spot Testnet modes.
"""

import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Optional
from urllib.parse import urlencode


class PaperExchangeClient:
    """Deterministic in-process exchange adapter for paper and fixture modes."""

    def __init__(self):
        self.orders = {}

    def execute(self, symbol: str, side: str, quantity: float, price: float, client_order_id: str) -> Dict:
        order = {
            "order_id": f"paper_{client_order_id}",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "status": "filled",
            "filled_quantity": quantity,
            "filled_price": price,
        }
        self.orders[client_order_id] = order
        return order

    def get_order(self, symbol: str, client_order_id: str) -> Dict:
        if client_order_id not in self.orders:
            raise ValueError(f"paper order not found: {client_order_id}")
        return self.orders[client_order_id]

    def get_open_positions(self):
        return []


class BinanceSpotTestnetClient:
    """Small Binance Spot Testnet REST adapter using signed order endpoints."""

    def __init__(self, config):
        self.base_url = config.BINANCE_TESTNET_BASE_URL.rstrip("/")
        self.api_key = getattr(config, "BINANCE_TESTNET_API_KEY", None)
        self.api_secret = getattr(config, "BINANCE_TESTNET_API_SECRET", None)
        self.recv_window = getattr(config, "BINANCE_RECV_WINDOW_MS", 5000)
        import requests
        self.session = requests.Session()

        if not self.api_key or not self.api_secret or "your-testnet" in str(self.api_key):
            raise ValueError("Binance testnet credentials are required for MODE='testnet'")

        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    def execute(self, symbol: str, side: str, quantity: float, price: float, client_order_id: str) -> Dict:
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": self._format_quantity(quantity),
            "newClientOrderId": client_order_id,
            "newOrderRespType": "FULL",
        }
        data = self._signed_request("POST", "/api/v3/order", params)
        return self._normalize_order(data, fallback_price=price)

    def get_order(self, symbol: str, client_order_id: str) -> Dict:
        data = self._signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "origClientOrderId": client_order_id},
        )
        return self._normalize_order(data)

    def get_open_positions(self):
        account = self._signed_request("GET", "/api/v3/account", {})
        positions = []
        for balance in account.get("balances", []):
            asset = balance.get("asset", "")
            free = float(balance.get("free", 0) or 0)
            locked = float(balance.get("locked", 0) or 0)
            quantity = free + locked
            if asset != "USDT" and quantity > 0:
                positions.append({
                    "coin": asset,
                    "side": "LONG",
                    "exchange_quantity": quantity,
                })
        return positions

    def _signed_request(self, method: str, path: str, params: Dict) -> Dict:
        signed_params = dict(params)
        signed_params["recvWindow"] = self.recv_window
        signed_params["timestamp"] = int(time.time() * 1000)
        query = urlencode(signed_params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        response = self.session.request(method, url, timeout=15)
        response.raise_for_status()
        return response.json()

    def _normalize_order(self, data: Dict, fallback_price: Optional[float] = None) -> Dict:
        executed_qty = float(data.get("executedQty", 0) or 0)
        quote_qty = float(data.get("cummulativeQuoteQty", 0) or 0)
        avg_price = (quote_qty / executed_qty) if executed_qty else (fallback_price or 0)
        fills = data.get("fills") or []
        fee_quantity = sum(float(fill.get("commission", 0) or 0) for fill in fills)
        fee_asset = fills[0].get("commissionAsset", "USDT") if fills else "USDT"

        return {
            "order_id": str(data.get("orderId", "")),
            "client_order_id": data.get("clientOrderId", ""),
            "status": self._normalize_status(data.get("status", "")),
            "filled_quantity": executed_qty,
            "filled_price": avg_price,
            "fee_asset": fee_asset,
            "fee_quantity": fee_quantity,
        }

    def _normalize_status(self, status: str) -> str:
        mapping = {
            "FILLED": "filled",
            "PARTIALLY_FILLED": "partially_filled",
            "CANCELED": "cancelled",
            "REJECTED": "failed",
            "EXPIRED": "failed",
            "NEW": "pending",
        }
        return mapping.get(status, status.lower())

    def _format_quantity(self, quantity: float) -> str:
        # Conservative precision until exchangeInfo lot-size rounding is added.
        return str(Decimal(str(quantity)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN))
