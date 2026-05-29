"""
LAYER E - STATE RECONCILER
Runs on EVERY startup before any order.
Reconciles vs Binance: exchange wins.
Stale state on startup: stand down until reconciliation complete.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class StateReconciler:
    """Reconciles local state with exchange."""

    def __init__(self, config, binance_client=None):
        self.config = config
        self.binance_client = binance_client
        self.last_reconciliation = None
        self.reconciliation_complete = False

    def reconcile_on_startup(self, local_positions: List[Dict]) -> tuple[bool, str]:
        """
        Reconcile local positions with exchange on startup.
        Returns: (success, message)
        """
        logger.info("Starting state reconciliation...")

        if not self.binance_client:
            if getattr(self.config, "MODE", "") == "testnet":
                return False, "testnet reconciliation requires an exchange client"
            self.reconciliation_complete = True
            self.last_reconciliation = datetime.now(timezone.utc)
            logger.info("Reconciliation complete (mock)")
            return True, "reconciliation complete (mock)"

        try:
            # Get exchange orders
            exchange_positions = self.binance_client.get_open_positions()

            # Compare and fix discrepancies
            reconciled = self._reconcile_positions(local_positions, exchange_positions)

            self.reconciliation_complete = True
            self.last_reconciliation = datetime.now(timezone.utc)
            logger.info(f"Reconciliation complete: {len(reconciled)} positions verified")

            return True, f"reconciled {len(reconciled)} positions"

        except Exception as e:
            logger.error(f"Reconciliation failed: {e}")
            return False, str(e)

    def _reconcile_positions(self, local: List[Dict], exchange: List[Dict]) -> List[Dict]:
        """
        Reconcile positions: exchange is source of truth.
        Returns: reconciled positions.
        """
        reconciled = []

        # CRITICAL CHECK: Local has positions but exchange is empty
        if local and not exchange:
            logger.error(f"CRITICAL: Local has {len(local)} positions but exchange is empty!")
            logger.error("This indicates orphaned positions that were closed externally.")
            logger.error("Positions will NOT be reopened. Manual verification required.")
            raise ValueError("local positions are not present on exchange")

        # Create lookup by order ID when available, otherwise by coin for spot balances.
        exchange_lookup = {
            p.get('order_id') or p.get('coin'): p
            for p in exchange
            if p.get('order_id') or p.get('coin')
        }

        for local_pos in local:
            position_key = local_pos.get('order_id') or local_pos.get('coin')
            if position_key in exchange_lookup:
                # Position exists on exchange; use exchange state
                reconciled.append(exchange_lookup[position_key])
                logger.debug(f"Position {position_key} verified with exchange")
            else:
                # Position missing from exchange; likely closed
                logger.warning(f"Position {position_key} not found on exchange (likely closed)")
                raise ValueError(f"local position {position_key} not found on exchange")

        # Check for positions on exchange not in local (new/manual)
        local_ids = {p.get('order_id') or p.get('coin') for p in local}
        for exchange_pos in exchange:
            position_key = exchange_pos.get('order_id') or exchange_pos.get('coin')
            if position_key not in local_ids:
                logger.warning(f"Unexpected position on exchange: {position_key}")
                raise ValueError(f"unexpected exchange position {position_key}")

        return reconciled

    def is_reconciliation_complete(self) -> bool:
        """Check if reconciliation complete."""
        return self.reconciliation_complete

    def get_status(self) -> Dict:
        """Get reconciliation status."""
        return {
            "complete": self.reconciliation_complete,
            "last_reconciliation": self.last_reconciliation.isoformat() if self.last_reconciliation else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
