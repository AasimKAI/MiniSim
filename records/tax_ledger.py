"""
LAYER F - TAX LEDGER
Append-only. Trade date, asset, qty, GBP value, fees (HMRC form).
Not tax advice. Audit trail for disposal reconstruction.
"""

import logging
import json
import uuid
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TaxLedger:
    """Append-only tax ledger for HMRC."""

    def __init__(self, config, ledger_file: str = "data/tax_ledger.jsonl"):
        self.config = config
        self.ledger_file = ledger_file
        self.entries = []
        self.currency = config.TAX_LEDGER_CURRENCY
        self.retain_fills = config.TAX_LEDGER_RETAIN_FILLS

    def record_trade(self, order: Dict, price_gbp: float, fx_rate: float) -> str:
        """
        Record trade for tax.
        Returns entry_id.
        """
        entry_id = str(uuid.uuid4())
        trade_id = str(uuid.uuid4())

        quantity = order.get('filled_quantity', 0)
        fee_quantity = order.get('fee_quantity', 0)
        fee_gbp = price_gbp * (fee_quantity / (order.get('price', 1) * quantity)) if quantity > 0 else 0

        total_gbp = (price_gbp * quantity) + fee_gbp

        entry = {
            "entry_id": entry_id,
            "trade_id": trade_id,
            "order_id": order.get('order_id', ''),
            "timestamp": self._now_iso(),
            "coin": order.get('coin', ''),
            "side": order.get('side', ''),
            "quantity": quantity,
            "price_gbp": price_gbp,
            "fee_asset": order.get('fee_asset', ''),
            "fee_quantity": fee_quantity,
            "fee_gbp": fee_gbp,
            "total_gbp": total_gbp,
            "fx_source": "manual",
            "fx_rate": fx_rate,
            "exchange_fill_hash": self._hash_order(order) if self.retain_fills else "",
            "schema_version": "1.0.0",
            "note": "Record for HMRC self-assessment. Not tax advice.",
        }

        self.entries.append(entry)
        self._append_to_file(entry)

        logger.info(f"Tax record: {order.get('coin')} {quantity} units at {price_gbp:.2f} GBP")
        return entry_id

    def _hash_order(self, order: Dict) -> str:
        """Create hash of order for verification."""
        import hashlib
        content = json.dumps(order, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _append_to_file(self, entry: Dict) -> None:
        """Append entry to ledger file."""
        try:
            from collector.utils import ensure_dir
            ensure_dir(self.config.DATA_DIR)
            with open(self.ledger_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to write tax ledger: {e}")

    def get_all(self) -> List[Dict]:
        """Get all tax entries."""
        return self.entries.copy()

    def get_for_coin(self, coin: str) -> List[Dict]:
        """Get entries for coin."""
        return [e for e in self.entries if e.get('coin') == coin]

    def get_summary(self) -> Dict:
        """Get tax summary by coin."""
        summary = {}
        for entry in self.entries:
            coin = entry.get('coin', '')
            if coin not in summary:
                summary[coin] = {
                    "trades": 0,
                    "quantity": 0,
                    "total_gbp": 0,
                    "total_fees_gbp": 0,
                }
            summary[coin]["trades"] += 1
            summary[coin]["quantity"] += entry.get('quantity', 0)
            summary[coin]["total_gbp"] += entry.get('total_gbp', 0)
            summary[coin]["total_fees_gbp"] += entry.get('fee_gbp', 0)

        return summary

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
