"""
Schema validators for all record types.
Validates records at boundaries between components.
Schema-first: validate before processing, reject invalid records, stand down if cannot rebuild.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


class AnalystView(Enum):
    """Possible views from analysts."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class VerdictStatus(Enum):
    """Status of analyst verdicts."""
    UNVALIDATED = "unvalidated"
    VALIDATED = "validated"
    FAILED = "failed"
    STALE_VALIDATION = "stale_validation"


class SignalDecision(Enum):
    """CEO decision outcomes."""
    ENTRY_BUY = "entry_buy"
    ENTRY_SELL = "entry_sell"
    STAND_DOWN = "stand_down"


class OrderStatus(Enum):
    """Order execution status."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DecisionLogStatus(Enum):
    """Decision log record status."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTED = "executed"
    EXITED = "exited"
    VETOED = "vetoed"


def validate_required_fields(data: Dict[str, Any], required: List[str]) -> None:
    """Validate all required fields present."""
    missing = [f for f in required if f not in data or data[f] is None]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")


def validate_enum_field(value: Any, enum_class: type) -> None:
    """Validate value is valid enum member."""
    valid_values = [e.value for e in enum_class]
    if value not in valid_values:
        raise ValueError(f"Invalid enum value '{value}'. Must be one of {valid_values}")


def validate_timestamp(ts: str) -> None:
    """Validate ISO 8601 timestamp."""
    try:
        datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid timestamp format: {ts}")


def validate_confidence(confidence: float) -> None:
    """Validate confidence is 0-1."""
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
        raise ValueError(f"Confidence must be 0-1, got {confidence}")


def validate_analyst_verdict(verdict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate analyst verdict record.

    Standard verdict shape:
    {
        "analyst": str,
        "coin": str,
        "view": "bullish"|"bearish"|"neutral",
        "confidence": 0-1,
        "reasoning": str,
        "timestamp": ISO8601,
        "data_age_seconds": int,
        "status": "unvalidated"|"validated"|"failed"|"stale_validation",
        "schema_version": str,
        (optional) "technical_signals": {...},
        (optional) "volume_signals": {...},
        (optional) "sentiment_score": 0-1,
    }
    """
    required = ["analyst", "coin", "view", "confidence", "reasoning", "timestamp", "data_age_seconds", "status"]
    validate_required_fields(verdict, required)

    validate_enum_field(verdict["view"], AnalystView)
    validate_enum_field(verdict["status"], VerdictStatus)
    validate_confidence(verdict["confidence"])
    validate_timestamp(verdict["timestamp"])

    if not isinstance(verdict["analyst"], str) or not verdict["analyst"]:
        raise ValueError(f"analyst must be non-empty string")
    if not isinstance(verdict["coin"], str) or not verdict["coin"]:
        raise ValueError(f"coin must be non-empty string")
    if not isinstance(verdict["reasoning"], str):
        raise ValueError(f"reasoning must be string")
    if not isinstance(verdict["data_age_seconds"], int) or verdict["data_age_seconds"] < 0:
        raise ValueError(f"data_age_seconds must be non-negative int")

    # Add schema version if missing
    if "schema_version" not in verdict:
        verdict["schema_version"] = SCHEMA_VERSION

    return verdict


def validate_signal_record(signal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate signal record (CEO decision).

    {
        "signal_id": str (unique),
        "decision": "entry_buy"|"entry_sell"|"stand_down",
        "coin": str,
        "view": "bullish"|"bearish"|"neutral",
        "confidence": 0-1,
        "bull_case": str,
        "bear_case": str,
        "regime": str,
        "timestamp": ISO8601,
        "ceo_model_name": str,
        "ceo_model_version": str,
        "ceo_timeout_sec": float,
        "ceo_validation_result": str,
        "is_big_trade": bool,
        "schema_version": str,
    }
    """
    required = [
        "signal_id", "decision", "coin", "view", "confidence",
        "bull_case", "bear_case", "regime", "timestamp",
        "ceo_model_name", "ceo_model_version", "ceo_timeout_sec", "ceo_validation_result", "is_big_trade"
    ]
    validate_required_fields(signal, required)

    validate_enum_field(signal["decision"], SignalDecision)
    validate_enum_field(signal["view"], AnalystView)
    validate_confidence(signal["confidence"])
    validate_timestamp(signal["timestamp"])

    if not isinstance(signal["signal_id"], str) or not signal["signal_id"]:
        raise ValueError("signal_id must be non-empty string")
    if not isinstance(signal["bull_case"], str):
        raise ValueError("bull_case must be string")
    if not isinstance(signal["bear_case"], str):
        raise ValueError("bear_case must be string")
    if not isinstance(signal["regime"], str):
        raise ValueError("regime must be string")
    if not isinstance(signal["is_big_trade"], bool):
        raise ValueError("is_big_trade must be boolean")

    if "schema_version" not in signal:
        signal["schema_version"] = SCHEMA_VERSION

    return signal


def validate_order_record(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate order execution record.

    {
        "order_id": str (exchange order ID),
        "client_order_id": str (signal_id/action - idempotent key),
        "signal_id": str,
        "coin": str,
        "side": "BUY"|"SELL",
        "quantity": float,
        "price": float,
        "status": "pending"|"filled"|"partially_filled"|"cancelled"|"failed",
        "filled_quantity": float,
        "filled_price": float,
        "fee_asset": str,
        "fee_quantity": float,
        "timestamp": ISO8601,
        "exchange_timestamp": ISO8601,
        "schema_version": str,
    }
    """
    required = [
        "client_order_id", "signal_id", "coin", "side", "quantity", "price",
        "status", "filled_quantity", "timestamp"
    ]
    validate_required_fields(order, required)

    validate_enum_field(order["status"], OrderStatus)
    validate_timestamp(order["timestamp"])

    if not isinstance(order["client_order_id"], str) or not order["client_order_id"]:
        raise ValueError("client_order_id must be non-empty string")
    if order["side"] not in ["BUY", "SELL"]:
        raise ValueError(f"side must be BUY or SELL, got {order['side']}")
    if not isinstance(order["quantity"], (int, float)) or order["quantity"] <= 0:
        raise ValueError("quantity must be positive number")
    if not isinstance(order["price"], (int, float)) or order["price"] <= 0:
        raise ValueError("price must be positive number")
    if not isinstance(order["filled_quantity"], (int, float)) or order["filled_quantity"] < 0:
        raise ValueError("filled_quantity must be non-negative number")

    if "schema_version" not in order:
        order["schema_version"] = SCHEMA_VERSION

    return order


def validate_position_record(position: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate open position record.

    {
        "position_id": str,
        "signal_id": str,
        "coin": str,
        "side": "LONG"|"SHORT",
        "entry_price": float,
        "entry_quantity": float,
        "entry_timestamp": ISO8601,
        "current_price": float,
        "current_timestamp": ISO8601,
        "stop_loss": float,
        "take_profit_targets": [float, ...],
        "trailing_stop": float,
        "trailing_stop_activated": bool,
        "thesis_condition": str (structured predicate),
        "max_hold_time_sec": float,
        "status": "open"|"closing"|"closed",
        "schema_version": str,
    }
    """
    required = [
        "position_id", "signal_id", "coin", "side", "entry_price", "entry_quantity",
        "entry_timestamp", "stop_loss", "take_profit_targets", "thesis_condition",
        "max_hold_time_sec", "status"
    ]
    validate_required_fields(position, required)

    validate_timestamp(position["entry_timestamp"])

    if position["side"] not in ["LONG", "SHORT"]:
        raise ValueError(f"side must be LONG or SHORT, got {position['side']}")
    if not isinstance(position["entry_price"], (int, float)) or position["entry_price"] <= 0:
        raise ValueError("entry_price must be positive")
    if not isinstance(position["entry_quantity"], (int, float)) or position["entry_quantity"] <= 0:
        raise ValueError("entry_quantity must be positive")
    if not isinstance(position["stop_loss"], (int, float)) or position["stop_loss"] <= 0:
        raise ValueError("stop_loss must be positive")
    if not isinstance(position["take_profit_targets"], list) or not position["take_profit_targets"]:
        raise ValueError("take_profit_targets must be non-empty list")
    if position["status"] not in ["open", "closing", "closed"]:
        raise ValueError(f"status must be open/closing/closed, got {position['status']}")

    if "schema_version" not in position:
        position["schema_version"] = SCHEMA_VERSION

    return position


def validate_exit_plan(exit_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate exit plan for open position.

    {
        "position_id": str,
        "entry_price": float,
        "stop_loss": float,
        "profit_targets": [
            {"target_price": float, "quantity_percent": float},
            ...
        ],
        "trailing_rule": {
            "enabled": bool,
            "percent": float,
        },
        "thesis_condition": {
            "condition_type": str,
            "parameters": {...},
            "prose_rationale": str,
        },
        "max_hold_time_sec": float,
        "timestamp": ISO8601,
        "schema_version": str,
    }
    """
    required = [
        "position_id", "entry_price", "stop_loss", "profit_targets",
        "trailing_rule", "thesis_condition", "max_hold_time_sec", "timestamp"
    ]
    validate_required_fields(exit_plan, required)

    validate_timestamp(exit_plan["timestamp"])

    if not isinstance(exit_plan["entry_price"], (int, float)) or exit_plan["entry_price"] <= 0:
        raise ValueError("entry_price must be positive")
    if not isinstance(exit_plan["stop_loss"], (int, float)) or exit_plan["stop_loss"] <= 0:
        raise ValueError("stop_loss must be positive")
    if not isinstance(exit_plan["profit_targets"], list) or not exit_plan["profit_targets"]:
        raise ValueError("profit_targets must be non-empty list")

    for target in exit_plan["profit_targets"]:
        if "target_price" not in target or "quantity_percent" not in target:
            raise ValueError("each profit_target must have target_price and quantity_percent")
        if not isinstance(target["target_price"], (int, float)) or target["target_price"] <= 0:
            raise ValueError("target_price must be positive")
        if not isinstance(target["quantity_percent"], (int, float)) or not (0 < target["quantity_percent"] <= 100):
            raise ValueError("quantity_percent must be 0-100")

    if not isinstance(exit_plan["trailing_rule"], dict):
        raise ValueError("trailing_rule must be dict")

    if not isinstance(exit_plan["thesis_condition"], dict):
        raise ValueError("thesis_condition must be dict")

    if "schema_version" not in exit_plan:
        exit_plan["schema_version"] = SCHEMA_VERSION

    return exit_plan


def validate_decision_log_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate decision log record.

    {
        "log_id": str,
        "signal_id": str,
        "status": "proposed"|"approved"|"executed"|"exited"|"vetoed",
        "coin": str,
        "decision": str,
        "timestamp": ISO8601,
        "reason": str,
        "schema_version": str,
    }
    """
    required = ["log_id", "signal_id", "status", "coin", "decision", "timestamp"]
    validate_required_fields(record, required)

    validate_enum_field(record["status"], DecisionLogStatus)
    validate_timestamp(record["timestamp"])

    if not isinstance(record["log_id"], str) or not record["log_id"]:
        raise ValueError("log_id must be non-empty string")
    if not isinstance(record["decision"], str):
        raise ValueError("decision must be string")

    if "schema_version" not in record:
        record["schema_version"] = SCHEMA_VERSION

    return record


def validate_tax_ledger_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate tax ledger entry (append-only).

    {
        "entry_id": str,
        "trade_id": str,
        "order_id": str,
        "timestamp": ISO8601,
        "coin": str,
        "quantity": float,
        "price_gbp": float,
        "fee_asset": str,
        "fee_quantity": float,
        "fee_gbp": float,
        "total_gbp": float,
        "fx_source": str,
        "fx_rate": float,
        "exchange_fill_hash": str,
        "schema_version": str,
    }
    """
    required = [
        "entry_id", "trade_id", "order_id", "timestamp", "coin",
        "quantity", "price_gbp", "fee_gbp", "total_gbp", "fx_source", "exchange_fill_hash"
    ]
    validate_required_fields(entry, required)

    validate_timestamp(entry["timestamp"])

    if not isinstance(entry["quantity"], (int, float)) or entry["quantity"] <= 0:
        raise ValueError("quantity must be positive")
    if not isinstance(entry["price_gbp"], (int, float)) or entry["price_gbp"] <= 0:
        raise ValueError("price_gbp must be positive")
    if not isinstance(entry["fee_gbp"], (int, float)) or entry["fee_gbp"] < 0:
        raise ValueError("fee_gbp must be non-negative")

    if "schema_version" not in entry:
        entry["schema_version"] = SCHEMA_VERSION

    return entry


def validate_reflection_lesson(lesson: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate reflection lesson record.

    {
        "lesson_id": str,
        "coin": str,
        "analyst": str,
        "pattern": str,
        "confidence": 0-1,
        "sample_size": int,
        "p_value": float,
        "is_provisional": bool,
        "timestamp": ISO8601,
        "schema_version": str,
    }
    """
    required = [
        "lesson_id", "coin", "analyst", "pattern", "confidence",
        "sample_size", "p_value", "is_provisional", "timestamp"
    ]
    validate_required_fields(lesson, required)

    validate_confidence(lesson["confidence"])
    validate_timestamp(lesson["timestamp"])

    if not isinstance(lesson["sample_size"], int) or lesson["sample_size"] <= 0:
        raise ValueError("sample_size must be positive int")
    if not isinstance(lesson["p_value"], (int, float)) or not (0 <= lesson["p_value"] <= 1):
        raise ValueError("p_value must be 0-1")
    if not isinstance(lesson["is_provisional"], bool):
        raise ValueError("is_provisional must be bool")

    if "schema_version" not in lesson:
        lesson["schema_version"] = SCHEMA_VERSION

    return lesson


def safe_validate(record: Dict[str, Any], validator_fn) -> tuple[bool, Optional[str]]:
    """
    Safe validation: returns (is_valid, error_message).
    Never raises; always returns result.
    """
    try:
        validator_fn(record)
        return True, None
    except Exception as e:
        return False, str(e)
