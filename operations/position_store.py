"""
Durable position and exposure state.
"""

from typing import Dict, Tuple

from collector.utils import atomic_write_json, read_json_safe


class PositionStore:
    """Persists open positions and exposure so restarts can resume exit management."""

    def __init__(self, config, state_file: str = None):
        self.config = config
        self.state_file = state_file or f"{config.STATE_DIR}/positions.json"

    def load(self) -> Tuple[Dict, float]:
        data = read_json_safe(self.state_file) or {}
        positions = data.get("positions", {})
        exposure = data.get("current_exposure_usd", 0.0)
        if not isinstance(positions, dict):
            positions = {}
        return positions, float(exposure or 0.0)

    def save(self, positions: Dict, current_exposure_usd: float) -> bool:
        return atomic_write_json(
            self.state_file,
            {
                "positions": positions,
                "current_exposure_usd": current_exposure_usd,
            },
            fsync=getattr(self.config, "ATOMIC_WRITE_FSYNC", True),
        )
