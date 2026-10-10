from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from . import config


@dataclass(frozen=True)
class Calculation:
    inputs: dict[str, Any]
    formula: str
    result: dict[str, Any]
    policy_citations: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "inputs": self.inputs,
            "formula": self.formula,
            "result": self.result,
            "policy_citations": list(self.policy_citations),
        }


def _citation(*keys: str) -> tuple[dict[str, Any], ...]:
    citations = []
    for key in keys:
        policy = config.POLICY_CITATIONS[key]
        if key.startswith("cancellation_"):
            section_keys = (
                keys[1:]
                if len(keys) > 1
                else (
                    "customer_cancellation",
                    "ridewise_cancellation",
                    "no_shows",
                    "scope",
                )
            )
            citations.extend(
                {
                    "doc": policy["doc"],
                    "version": policy["version"],
                    "effective_date": policy["effective_date"],
                    "section": policy[section_key]["section"],
                    "page": policy[section_key]["page"],
                }
                for section_key in section_keys
            )
            break
        elif key == "gst":
            citations.append(
                {
                    "doc": policy["doc"],
                    "version": policy["version"],
                    "effective_date": policy["effective_date"],
                    "section": policy["section"],
                    "page": policy["page"],
                }
            )
        else:
            citations.append(dict(policy))
    unique = {tuple(sorted(item.items())): item for item in citations}
    return tuple(unique.values())


def _decimal(value: Any, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a valid number.") from exc
    if not amount.is_finite():
        raise ValueError(f"{name} must be finite.")
    return amount


def _money(value: Decimal) -> Decimal:
    return value.quantize(config.MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _utc_datetime(value: str | datetime, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be a valid ISO datetime.") from exc
    else:
        raise ValueError(f"{name} must be a UTC datetime or ISO datetime string.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=config.UTC)
    return parsed.astimezone(config.UTC)


def _booking_datetime(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, config.IST)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("booking_date must be a valid ISO date or datetime.") from exc
    else:
        raise ValueError("booking_date must be a date or datetime.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=config.UTC)
    return parsed.astimezone(config.IST)


def _payment_value(payment: Mapping[str, Any], field: str, default: Any = 0) -> Any:
    return payment.get(field, default)


def calculate_gst(base_amount: Any) -> Calculation:
    """Calculate GST separately from a GST-exclusive payment amount."""
    base = _decimal(base_amount, "base_amount")
    gst = _money(base * config.GST_RATE)
    return Calculation(
        inputs={"base_amount_excluding_gst": base, "gst_rate": config.GST_RATE},
        formula=(
            "GST = round_half_up(base_amount_excluding_gst × "
            f"{config.GST_RATE * config.PERCENT_DISPLAY_MULTIPLIER}% , 2)"
        ),
        result={"gst_amount": gst, "total_including_gst": _money(base + gst)},
        policy_citations=_citation("gst"),
    )


def calculate_rental_charge(
    *,
    duration_hours: int,
    hourly_rate: Any,
    daily_rate: Any,
) -> Calculation:
    """Compute rental principal using full-day blocks and a capped remainder."""
    if isinstance(duration_hours, bool) or not isinstance(duration_hours, int):
        raise ValueError("duration_hours must be a whole number of hours.")
    if duration_hours < config.MINIMUM_RENTAL_HOURS:
        raise ValueError(
            "duration_hours must be at least "
            f"{config.MINIMUM_RENTAL_HOURS}."
        )
    hourly = _decimal(hourly_rate, "hourly_rate")
    daily = _decimal(daily_rate, "daily_rate")
    if hourly < 0 or daily < 0:
        raise ValueError("hourly_rate and daily_rate cannot be negative.")

    full_days, remainder_hours = divmod(duration_hours, config.HOURS_PER_DAY)
    remainder_hourly = hourly * remainder_hours
    remainder_charge = min(remainder_hourly, daily)
    principal = _money(daily * full_days + remainder_charge)
    gst = _money(principal * config.GST_RATE)
    return Calculation(
        inputs={
            "duration_hours": duration_hours,
            "hourly_rate": hourly,
            "daily_rate": daily,
            "full_24_hour_blocks": full_days,
            "remaining_hours": remainder_hours,
            "remaining_hourly_charge_before_daily_cap": _money(remainder_hourly),
        },
        formula=(
            "Rental principal = full 24-hour blocks × daily_rate + "
            "min(remaining_hours × hourly_rate, daily_rate); "
            "GST is calculated separately at the configured rate."
        ),
        result={
            "rental_charge_excluding_gst": principal,
            "gst_amount": gst,
            "total_including_gst": _money(principal + gst),
        },
        policy_citations=_citation("rental_charge", "rental_gst"),
    )


def _cancellation_version(booking_date: str | date | datetime) -> str:
    local_booking_time = _booking_datetime(booking_date)
    if local_booking_time < config.CANCELLATION_V2_EFFECTIVE_AT:
        return config.CANCELLATION_V1_VERSION
    return config.CANCELLATION_V2_VERSION


def _customer_refund_rate(version: str, hours_before_pickup: timedelta) -> Decimal:
    for minimum_lead_time, refund_rate in config.CANCELLATION_REFUND_BRACKETS[
        version
    ]:
        if hours_before_pickup >= minimum_lead_time:
            return refund_rate
    return Decimal("0")


def _successful_payments(
    payments: Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    records = list(payments)
    unknown_statuses = {
        str(_payment_value(payment, "payment_status", "")).upper()
        for payment in records
    } - (config.NON_SUCCESS_PAYMENT_STATUSES | {config.SUCCESS_PAYMENT_STATUS})
    if unknown_statuses:
        raise ValueError(
            "Unsupported payment status: " + ", ".join(sorted(unknown_statuses))
        )
    successful = [
        payment
        for payment in records
        if str(_payment_value(payment, "payment_status", "")).upper()
        == config.SUCCESS_PAYMENT_STATUS
    ]
    pending_or_failed = [
        payment
        for payment in records
        if str(_payment_value(payment, "payment_status", "")).upper()
        in config.NON_SUCCESS_PAYMENT_STATUSES
    ]
    return successful, pending_or_failed


def _payment_summary(payments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: _payment_value(payment, key)
            for key in ("payment_type", "payment_status", "amount", "gst_amount")
        }
        for payment in payments
    ]


def calculate_cancellation_refund(
    *,
    booking_date: str | date | datetime,
    scheduled_start: str | datetime,
    booking_status: str,
    payments: Iterable[Mapping[str, Any]],
    cancelled_at: str | datetime | None = None,
) -> Calculation:
    """Calculate rental-principal and GST refund using the booking-date policy."""
    status = booking_status.strip().upper()
    version = _cancellation_version(booking_date)
    successful, non_successful = _successful_payments(payments)

    booking_payments = [
        payment
        for payment in successful
        if str(_payment_value(payment, "payment_type", "")).upper()
        == config.BOOKING_PAYMENT_TYPE
    ]
    prior_refunds = [
        payment
        for payment in successful
        if str(_payment_value(payment, "payment_type", "")).upper()
        == config.REFUND_PAYMENT_TYPE
    ]
    paid_principal = sum(
        (_decimal(_payment_value(payment, "amount"), "payment.amount")
         for payment in booking_payments),
        Decimal("0"),
    )
    paid_gst = sum(
        (_decimal(_payment_value(payment, "gst_amount"), "payment.gst_amount")
         for payment in booking_payments),
        Decimal("0"),
    )
    already_refunded_principal = abs(
        sum(
            (_decimal(_payment_value(payment, "amount"), "payment.amount")
             for payment in prior_refunds),
            Decimal("0"),
        )
    )
    already_refunded_gst = abs(
        sum(
            (_decimal(_payment_value(payment, "gst_amount"), "payment.gst_amount")
             for payment in prior_refunds),
            Decimal("0"),
        )
    )

    pickup_utc = _utc_datetime(scheduled_start, "scheduled_start")
    cancellation_utc = (
        _utc_datetime(cancelled_at, "cancelled_at")
        if cancelled_at is not None
        else None
    )

    if status == config.NO_SHOW_STATUS:
        refund_rate = Decimal("0")
    elif status == config.RIDEWISE_CANCEL_STATUS:
        refund_rate = Decimal("1")
    elif status == config.CUSTOMER_CANCEL_STATUS:
        if cancellation_utc is None:
            raise ValueError("cancelled_at is required for a customer cancellation.")
        if cancellation_utc >= pickup_utc:
            raise ValueError("Customer cancellation must be before scheduled pickup.")
        refund_rate = _customer_refund_rate(
            version, pickup_utc - cancellation_utc
        )
    else:
        raise ValueError("booking_status must be CNL_U, CNL_S, or NSH.")

    eligible_principal = _money(paid_principal * refund_rate)
    eligible_gst = _money(paid_gst * refund_rate)
    refund_principal = max(
        Decimal("0"), _money(eligible_principal - already_refunded_principal)
    )
    refund_gst = max(Decimal("0"), _money(eligible_gst - already_refunded_gst))
    citation_key = (
        "cancellation_v1"
        if version == config.CANCELLATION_V1_VERSION
        else "cancellation_v2"
    )
    cancellation_section = {
        config.CUSTOMER_CANCEL_STATUS: "customer_cancellation",
        config.RIDEWISE_CANCEL_STATUS: "ridewise_cancellation",
        config.NO_SHOW_STATUS: "no_shows",
    }[status]

    return Calculation(
        inputs={
            "booking_date": booking_date,
            "booking_time_ist": _booking_datetime(booking_date).isoformat(),
            "policy_version": version,
            "scheduled_start_utc": pickup_utc.isoformat(),
            "cancelled_at_utc": (
                cancellation_utc.isoformat() if cancellation_utc else None
            ),
            "booking_status": status,
            "successful_booking_payments": _payment_summary(booking_payments),
            "successful_prior_refund_payments": _payment_summary(prior_refunds),
            "failed_or_pending_payments": _payment_summary(non_successful),
            "paid_rental_principal_excluding_gst": _money(paid_principal),
            "paid_rental_gst": _money(paid_gst),
        },
        formula=(
            "Select policy using booking time in IST; apply its refund rate to "
            "SUCCESS BOOKING payment principal and GST separately; subtract "
            "SUCCESS REFUND records already issued, floored at zero. "
            "NSH = 0%; CNL_S = 100%."
        ),
        result={
            "refund_rate": refund_rate,
            "eligible_principal_refund": eligible_principal,
            "eligible_gst_refund": eligible_gst,
            "already_refunded_principal": _money(already_refunded_principal),
            "already_refunded_gst": _money(already_refunded_gst),
            "principal_refund_due": refund_principal,
            "gst_refund_due": refund_gst,
            "total_refund_due": _money(refund_principal + refund_gst),
        },
        policy_citations=_citation(citation_key, "scope", cancellation_section),
    )


def calculate_tier_benefit(tier: str) -> Calculation:
    normalized_tier = tier.strip().upper()
    if normalized_tier not in config.TIER_LATE_GRACE:
        raise ValueError("tier must be STANDARD, SILVER, or GOLD.")
    grace = config.TIER_LATE_GRACE[normalized_tier]
    return Calculation(
        inputs={"customer_tier": normalized_tier},
        formula="Use the late-return grace period for the customer tier.",
        result={
            "late_return_grace_minutes": int(grace.total_seconds() / 60),
            "late_return_grace": grace,
        },
        policy_citations=_citation("tier_benefits"),
    )


def calculate_late_return_penalty(
    *,
    scheduled_return: str | datetime,
    actual_return: str | datetime,
    hourly_rate: Any,
    tier: str,
) -> Calculation:
    scheduled_utc = _utc_datetime(scheduled_return, "scheduled_return")
    actual_utc = _utc_datetime(actual_return, "actual_return")
    hourly_rate_amount = _decimal(hourly_rate, "hourly_rate")
    if hourly_rate_amount < 0:
        raise ValueError("hourly_rate cannot be negative.")
    normalized_tier = tier.strip().upper()
    if normalized_tier not in config.TIER_LATE_GRACE:
        raise ValueError("tier must be STANDARD, SILVER, or GOLD.")

    lateness = max(timedelta(0), actual_utc - scheduled_utc)
    grace = config.TIER_LATE_GRACE[normalized_tier]
    if lateness <= grace:
        charged_hours = 0
    else:
        elapsed_seconds = int(lateness.total_seconds())
        interval_seconds = int(config.LATE_BILLING_INTERVAL.total_seconds())
        charged_hours = (
            elapsed_seconds + interval_seconds - 1
        ) // interval_seconds
    principal = _money(
        hourly_rate_amount * config.LATE_FEE_MULTIPLIER * charged_hours
    )
    gst = _money(principal * config.GST_RATE)
    return Calculation(
        inputs={
            "scheduled_return_utc": scheduled_utc.isoformat(),
            "actual_return_utc": actual_utc.isoformat(),
            "lateness": lateness,
            "customer_tier": normalized_tier,
            "grace_period": grace,
            "hourly_rate": hourly_rate_amount,
        },
        formula=(
            "If lateness <= tier grace, fee = 0; otherwise charge the full "
            "lateness: ceil(lateness / "
            f"{config.LATE_BILLING_INTERVAL}) × hourly_rate × "
            f"{config.LATE_FEE_MULTIPLIER}; add GST at "
            f"{config.GST_RATE * config.PERCENT_DISPLAY_MULTIPLIER}%."
        ),
        result={
            "charged_hours": charged_hours,
            "penalty_excluding_gst": principal,
            "gst_amount": gst,
            "total_penalty_including_gst": _money(principal + gst),
        },
        policy_citations=_citation("late_return", "tier_benefits", "gst"),
    )


def calculate_damage_charge(
    *,
    claim_status: str,
    assessed_cost: Any,
    damage_category: str | None = None,
) -> Calculation:
    status = claim_status.strip().upper()
    if status not in {
        config.DAMAGE_CHARGE_STATUS,
        *config.NON_CHARGEABLE_DAMAGE_STATUSES,
    }:
        raise ValueError("claim_status must be OPEN, CHARGED, DISPUTED, or WAIVED.")
    if assessed_cost is None and status != config.DAMAGE_CHARGE_STATUS:
        cost = Decimal("0")
    else:
        cost = _decimal(assessed_cost, "assessed_cost")
    if cost < 0:
        raise ValueError("assessed_cost cannot be negative.")
    principal = cost if status == config.DAMAGE_CHARGE_STATUS else Decimal("0")
    principal = _money(principal)
    gst = _money(principal * config.GST_RATE)
    return Calculation(
        inputs={
            "claim_status": status,
            "assessed_cost": cost,
            "damage_category": damage_category,
        },
        formula=(
            "CHARGED: assessed cost; OPEN, DISPUTED, or WAIVED: no charge; "
            f"GST = charge × {config.GST_RATE * config.PERCENT_DISPLAY_MULTIPLIER}%."
        ),
        result={
            "charge_excluding_gst": principal,
            "gst_amount": gst,
            "total_charge_including_gst": _money(principal + gst),
        },
        policy_citations=_citation("damage", "gst"),
    )


def calculate_ev_battery_charge(
    *,
    vehicle_type: str,
    return_battery_pct: Any,
) -> Calculation:
    normalized_type = vehicle_type.strip().upper()
    battery = _decimal(return_battery_pct, "return_battery_pct")
    if normalized_type not in config.EV_TYPES:
        raise ValueError("vehicle_type must be EV_SCOOTER or EV_BIKE.")
    if not config.BATTERY_PERCENT_MIN <= battery <= config.BATTERY_PERCENT_MAX:
        raise ValueError(
            "return_battery_pct must be between "
            f"{config.BATTERY_PERCENT_MIN} and {config.BATTERY_PERCENT_MAX}."
        )
    principal = (
        config.EV_LOW_BATTERY_FEE
        if battery < config.EV_LOW_BATTERY_THRESHOLD_PCT
        else Decimal("0")
    )
    gst = _money(principal * config.GST_RATE)
    return Calculation(
        inputs={
            "vehicle_type": normalized_type,
            "return_battery_pct": battery,
        },
        formula=(
            "If EV return battery < "
            f"{config.EV_LOW_BATTERY_THRESHOLD_PCT}%, charge "
            f"₹{config.EV_LOW_BATTERY_FEE} per rental; otherwise charge ₹0; "
            f"add GST at {config.GST_RATE * config.PERCENT_DISPLAY_MULTIPLIER}%."
        ),
        result={
            "charge_excluding_gst": principal,
            "gst_amount": gst,
            "total_charge_including_gst": _money(principal + gst),
        },
        policy_citations=_citation("ev_battery", "gst"),
    )
