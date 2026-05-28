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
            # Mock reconciliation for testing
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

        # Create lookup by order ID
        exchange_lookup = {p.get('order_id'): p for p in exchange}

        for local_pos in local:
            order_id = local_pos.get('order_id')
            if order_id in exchange_lookup:
                # Position exists on exchange; use exchange state
                reconciled.append(exchange_lookup[order_id])
                logger.debug(f"Position {order_id} verified with exchange")
            else:
                # Position missing from exchange; likely closed
                logger.warning(f"Position {order_id} not found on exchange (likely closed)")

        # Check for positions on exchange not in local (new/manual)
        local_ids = {p.get('order_id') for p in local}
        for exchange_pos in exchange:
            if exchange_pos.get('order_id') not in local_ids:
                logger.warning(f"Unexpected position on exchange: {exchange_pos.get('order_id')}")
                reconciled.append(exchange_pos)

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
