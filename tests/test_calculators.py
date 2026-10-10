import unittest
from datetime import datetime, timezone
from decimal import Decimal

from src.calculators import (
    calculate_cancellation_refund,
    calculate_damage_charge,
    calculate_ev_battery_charge,
    calculate_gst,
    calculate_late_return_penalty,
    calculate_rental_charge,
    calculate_tier_benefit,
)


def booking_payment(
    amount: str,
    gst_amount: str,
    *,
    status: str = "SUCCESS",
    payment_type: str = "BOOKING",
) -> dict[str, str]:
    return {
        "payment_type": payment_type,
        "payment_status": status,
        "amount": amount,
        "gst_amount": gst_amount,
    }


class CancellationRefundTests(unittest.TestCase):
    def calculate(self, **kwargs):
        return calculate_cancellation_refund(
            booking_date="2026-06-30T18:29:59Z",
            scheduled_start="2026-07-01T12:00:00Z",
            booking_status="CNL_U",
            cancelled_at="2026-07-01T00:00:00Z",
            payments=[
                booking_payment("1000", "180"),
                booking_payment("500", "90", status="FAILED"),
                booking_payment("300", "54", status="PENDING"),
                booking_payment("500", "0", payment_type="DEPOSIT"),
                booking_payment("-100", "-18", payment_type="REFUND"),
            ],
            **kwargs,
        )

    def test_v1_refund_slab_uses_booking_time_in_ist(self) -> None:
        result = self.calculate()
        self.assertEqual(result.inputs["policy_version"], "1")
        self.assertEqual(result.result["refund_rate"], Decimal("0.50"))
        self.assertEqual(result.result["principal_refund_due"], Decimal("400.00"))
        self.assertEqual(result.result["gst_refund_due"], Decimal("72.00"))
        self.assertEqual(result.result["total_refund_due"], Decimal("472.00"))
        self.assertEqual(len(result.inputs["failed_or_pending_payments"]), 2)
        self.assertTrue(result.policy_citations)

    def test_v2_refund_slab_applies_at_ist_cutoff(self) -> None:
        result = calculate_cancellation_refund(
            booking_date=datetime(2026, 6, 30, 18, 30, tzinfo=timezone.utc),
            scheduled_start="2026-07-01T12:00:00Z",
            cancelled_at="2026-07-01T00:00:00Z",
            booking_status="CNL_U",
            payments=[booking_payment("1000", "180")],
        )
        self.assertEqual(result.inputs["policy_version"], "2")
        self.assertEqual(result.result["refund_rate"], Decimal("0.75"))
        self.assertEqual(result.result["total_refund_due"], Decimal("885.00"))
        self.assertEqual(
            {citation["version"] for citation in result.policy_citations}, {"2"}
        )

    def test_ridewise_cancellation_refunds_all_successful_booking_payment(self):
        result = calculate_cancellation_refund(
            booking_date="2026-08-01T00:00:00Z",
            scheduled_start="2026-08-03T00:00:00Z",
            booking_status="CNL_S",
            payments=[
                booking_payment("100", "18"),
                booking_payment("50", "9", status="FAILED"),
            ],
        )
        self.assertEqual(result.result["refund_rate"], Decimal("1"))
        self.assertEqual(result.result["total_refund_due"], Decimal("118.00"))
        self.assertEqual(len(result.inputs["failed_or_pending_payments"]), 1)

    def test_no_show_has_no_refund(self) -> None:
        result = calculate_cancellation_refund(
            booking_date="2026-08-01T00:00:00Z",
            scheduled_start="2026-08-03T00:00:00Z",
            booking_status="NSH",
            payments=[booking_payment("100", "18")],
        )
        self.assertEqual(result.result["total_refund_due"], Decimal("0.00"))

    def test_cancellation_requires_time_and_before_pickup(self) -> None:
        shared = {
            "booking_date": "2026-06-01T00:00:00Z",
            "scheduled_start": "2026-06-02T00:00:00Z",
            "booking_status": "CNL_U",
            "payments": [],
        }
        with self.assertRaisesRegex(ValueError, "cancelled_at is required"):
            calculate_cancellation_refund(**shared)
        with self.assertRaisesRegex(ValueError, "before scheduled pickup"):
            calculate_cancellation_refund(
                **shared, cancelled_at="2026-06-02T00:00:00Z"
            )

    def test_non_success_payments_are_not_paid_and_unknown_status_fails(self) -> None:
        result = calculate_cancellation_refund(
            booking_date="2026-06-01T00:00:00Z",
            scheduled_start="2026-06-02T00:00:00Z",
            cancelled_at="2026-06-01T00:00:00Z",
            booking_status="CNL_U",
            payments=[
                booking_payment("100", "18", status="FAILED"),
                booking_payment("50", "9", status="PENDING"),
            ],
        )
        self.assertEqual(result.result["total_refund_due"], Decimal("0.00"))
        with self.assertRaisesRegex(ValueError, "Unsupported payment status"):
            calculate_cancellation_refund(
                booking_date="2026-06-01T00:00:00Z",
                scheduled_start="2026-06-02T00:00:00Z",
                cancelled_at="2026-06-01T00:00:00Z",
                booking_status="CNL_U",
                payments=[booking_payment("100", "18", status="PROCESSING")],
            )

    def test_multiple_success_payments_and_negative_refund_are_netted(self) -> None:
        result = calculate_cancellation_refund(
            booking_date="2026-07-01T00:00:00Z",
            scheduled_start="2026-07-03T00:00:00Z",
            booking_status="CNL_S",
            payments=[
                booking_payment("500", "90"),
                booking_payment("300", "54"),
                booking_payment("-200", "-36", payment_type="REFUND"),
            ],
        )
        self.assertEqual(
            result.result["eligible_principal_refund"], Decimal("800.00")
        )
        self.assertEqual(
            result.result["already_refunded_principal"], Decimal("200.00")
        )
        self.assertEqual(result.result["principal_refund_due"], Decimal("600.00"))
        self.assertEqual(result.result["gst_refund_due"], Decimal("108.00"))
        self.assertEqual(result.result["total_refund_due"], Decimal("708.00"))


class GSTTests(unittest.TestCase):
    def test_gst_is_calculated_separately(self) -> None:
        result = calculate_gst("100.01")
        self.assertEqual(result.result["gst_amount"], Decimal("18.00"))
        self.assertEqual(result.result["total_including_gst"], Decimal("118.01"))
        self.assertIn("base_amount_excluding_gst", result.inputs)


class RentalChargeTests(unittest.TestCase):
    def test_policy_examples_at_80_hourly_and_700_daily(self) -> None:
        expected = {
            4: Decimal("320.00"),
            10: Decimal("700.00"),
            24: Decimal("700.00"),
            27: Decimal("940.00"),
        }
        for hours, charge in expected.items():
            with self.subTest(hours=hours):
                result = calculate_rental_charge(
                    duration_hours=hours,
                    hourly_rate="80",
                    daily_rate="700",
                )
                self.assertEqual(
                    result.result["rental_charge_excluding_gst"], charge
                )
                self.assertTrue(result.policy_citations)

    def test_minimum_and_whole_hour_validation(self) -> None:
        for duration in (1, 1.5, True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                calculate_rental_charge(
                    duration_hours=duration,
                    hourly_rate="80",
                    daily_rate="700",
                )


class LateReturnTests(unittest.TestCase):
    def calculate(self, minutes_late: int, tier: str = "STANDARD"):
        scheduled = datetime(2026, 1, 1, tzinfo=timezone.utc)
        actual = scheduled.replace(
            minute=minutes_late % 60,
            hour=(minutes_late // 60) % 24,
        )
        return calculate_late_return_penalty(
            scheduled_return=scheduled,
            actual_return=actual,
            hourly_rate="100",
            tier=tier,
        )

    def test_any_part_of_hour_is_rounded_up_and_gst_added(self) -> None:
        result = self.calculate(61)
        self.assertEqual(result.result["charged_hours"], 2)
        self.assertEqual(result.result["penalty_excluding_gst"], Decimal("300.00"))
        self.assertEqual(result.result["gst_amount"], Decimal("54.00"))
        self.assertEqual(
            result.result["total_penalty_including_gst"], Decimal("354.00")
        )

    def test_gold_grace_and_full_lateness_after_grace(self) -> None:
        within_grace = calculate_late_return_penalty(
            scheduled_return="2026-01-01T00:00:00Z",
            actual_return="2026-01-01T00:30:00Z",
            hourly_rate="100",
            tier="GOLD",
        )
        beyond_grace = calculate_late_return_penalty(
            scheduled_return="2026-01-01T00:00:00Z",
            actual_return="2026-01-01T00:30:01Z",
            hourly_rate="100",
            tier="GOLD",
        )
        self.assertEqual(within_grace.result["charged_hours"], 0)
        self.assertEqual(beyond_grace.result["charged_hours"], 1)
        self.assertEqual(
            beyond_grace.result["penalty_excluding_gst"], Decimal("150.00")
        )

    def test_offset_timestamps_are_compared_as_instants(self) -> None:
        result = calculate_late_return_penalty(
            scheduled_return="2026-01-01T05:30:00+05:30",
            actual_return="2026-01-01T00:00:01Z",
            hourly_rate="100",
            tier="SILVER",
        )
        self.assertEqual(result.result["charged_hours"], 1)
        self.assertEqual(
            result.inputs["scheduled_return_utc"], "2026-01-01T00:00:00+00:00"
        )


class DamageChargeTests(unittest.TestCase):
    def test_charged_damage_includes_separate_gst(self) -> None:
        result = calculate_damage_charge(
            claim_status="CHARGED", assessed_cost="200.00"
        )
        self.assertEqual(result.result["charge_excluding_gst"], Decimal("200.00"))
        self.assertEqual(result.result["gst_amount"], Decimal("36.00"))
        self.assertEqual(
            result.result["total_charge_including_gst"], Decimal("236.00")
        )

    def test_non_chargeable_and_not_yet_assessed_damage(self) -> None:
        for status in ("OPEN", "DISPUTED", "WAIVED"):
            with self.subTest(status=status):
                result = calculate_damage_charge(
                    claim_status=status, assessed_cost=None
                )
                self.assertEqual(
                    result.result["total_charge_including_gst"], Decimal("0.00")
                )


class TierAndBatteryTests(unittest.TestCase):
    def test_tier_grace_periods(self) -> None:
        expected = {"STANDARD": 0, "SILVER": 0, "GOLD": 30}
        for tier, minutes in expected.items():
            with self.subTest(tier=tier):
                result = calculate_tier_benefit(tier)
                self.assertEqual(
                    result.result["late_return_grace_minutes"], minutes
                )
                self.assertTrue(result.policy_citations)

    def test_ev_battery_threshold_is_strictly_below_ten_percent(self) -> None:
        below = calculate_ev_battery_charge(
            vehicle_type="EV_BIKE", return_battery_pct="9.99"
        )
        at_threshold = calculate_ev_battery_charge(
            vehicle_type="EV_SCOOTER", return_battery_pct="10"
        )
        self.assertEqual(
            below.result["total_charge_including_gst"], Decimal("177.00")
        )
        self.assertEqual(
            at_threshold.result["total_charge_including_gst"], Decimal("0.00")
        )

    def test_battery_level_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            calculate_ev_battery_charge(
                vehicle_type="EV_BIKE", return_battery_pct="101"
            )


if __name__ == "__main__":
    unittest.main()
