from datetime import datetime, timedelta, timezone
from decimal import Decimal

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

CANCELLATION_V2_EFFECTIVE_AT = datetime(2026, 7, 1, 0, 0, tzinfo=IST)
CANCELLATION_V1_VERSION = "1"
CANCELLATION_V2_VERSION = "2"
CANCELLATION_EFFECTIVE_DATES = {
    CANCELLATION_V1_VERSION: datetime(2025, 1, 1, 0, 0, tzinfo=IST),
    CANCELLATION_V2_VERSION: CANCELLATION_V2_EFFECTIVE_AT,
}

CANCELLATION_BOOKING_CUTOFF_BRACKETS = (
    (timedelta(hours=48), Decimal("1")),
    (timedelta(hours=12), Decimal("0.75")),
    (timedelta(hours=2), Decimal("0.25")),
    (timedelta(0), Decimal("0")),
)
CANCELLATION_REFUND_BRACKETS = {
    CANCELLATION_V1_VERSION: (
        (timedelta(hours=24), Decimal("1")),
        (timedelta(hours=6), Decimal("0.50")),
        (timedelta(0), Decimal("0")),
    ),
    CANCELLATION_V2_VERSION: CANCELLATION_BOOKING_CUTOFF_BRACKETS,
}

GST_RATE = Decimal("0.18")
MONEY_QUANTUM = Decimal("0.01")
HOURS_PER_DAY = 24
MINIMUM_RENTAL_HOURS = 2
RENTAL_DAY_BLOCK = timedelta(hours=HOURS_PER_DAY)
LATE_FEE_MULTIPLIER = Decimal("1.5")
LATE_BILLING_INTERVAL = timedelta(hours=1)
EV_LOW_BATTERY_THRESHOLD_PCT = Decimal("10")
EV_LOW_BATTERY_FEE = Decimal("150")
BATTERY_PERCENT_MIN = Decimal("0")
BATTERY_PERCENT_MAX = Decimal("100")
PERCENT_DISPLAY_MULTIPLIER = Decimal("100")
TIER_LATE_GRACE = {
    "STANDARD": timedelta(0),
    "SILVER": timedelta(0),
    "GOLD": timedelta(minutes=30),
}

BOOKING_PAYMENT_TYPE = "BOOKING"
REFUND_PAYMENT_TYPE = "REFUND"
SUCCESS_PAYMENT_STATUS = "SUCCESS"
NON_SUCCESS_PAYMENT_STATUSES = frozenset({"FAILED", "PENDING"})
CUSTOMER_CANCEL_STATUS = "CNL_U"
RIDEWISE_CANCEL_STATUS = "CNL_S"
NO_SHOW_STATUS = "NSH"
DAMAGE_CHARGE_STATUS = "CHARGED"
NON_CHARGEABLE_DAMAGE_STATUSES = frozenset({"OPEN", "DISPUTED", "WAIVED"})
EV_TYPES = frozenset({"EV_SCOOTER", "EV_BIKE"})

POLICY_CITATIONS = {
    "cancellation_v1": {
        "doc": "02_Cancellation_and_Refund_Policy_v1.pdf",
        "version": CANCELLATION_V1_VERSION,
        "effective_date": "2025-01-01",
        "scope": {
            "section": "Scope",
            "page": 1,
        },
        "customer_cancellation": {
            "section": "1. Cancellation by the customer",
            "page": 1,
        },
        "ridewise_cancellation": {
            "section": "2. Cancellation by RideWise",
            "page": 1,
        },
        "no_shows": {
            "section": "3. No-shows",
            "page": 1,
        },
    },
    "cancellation_v2": {
        "doc": "03_Cancellation_and_Refund_Policy_v2.pdf",
        "version": CANCELLATION_V2_VERSION,
        "effective_date": "2026-07-01T00:00:00+05:30",
        "scope": {
            "section": "Scope",
            "page": 1,
        },
        "customer_cancellation": {
            "section": "1. Cancellation by the customer; Annexure 1: Approved refund schedule",
            "page": 2,
        },
        "ridewise_cancellation": {
            "section": "2. Cancellation by RideWise; Annexure 1: Approved refund schedule",
            "page": 2,
        },
        "no_shows": {
            "section": "3. No-shows; Annexure 1: Approved refund schedule",
            "page": 2,
        },
    },
    "late_return": {
        "doc": "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
        "version": "2.1",
        "effective_date": "2025-01-01",
        "section": "1. Late return fee",
        "page": 1,
    },
    "rental_charge": {
        "doc": "01_Rental_Agreement_and_Terms.pdf",
        "version": "3.0",
        "effective_date": "2025-01-01",
        "section": "4. Rental charges",
        "page": 1,
    },
    "rental_gst": {
        "doc": "01_Rental_Agreement_and_Terms.pdf",
        "version": "3.0",
        "effective_date": "2025-01-01",
        "section": "4.3 GST",
        "page": 2,
    },
    "damage": {
        "doc": "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
        "version": "2.1",
        "effective_date": "2025-01-01",
        "section": "3. Damage",
        "page": 2,
    },
    "tier_benefits": {
        "doc": "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
        "version": "2.1",
        "effective_date": "2025-01-01",
        "section": "Annexure A: Tier benefits",
        "page": 3,
    },
    "ev_battery": {
        "doc": "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
        "version": "2.1",
        "effective_date": "2025-01-01",
        "section": "2. EV low-battery charging fee",
        "page": 2,
    },
    "gst": {
        "doc": "04_Late_Return_and_Damage_Penalty_Schedule.pdf",
        "version": "2.1",
        "effective_date": "2025-01-01",
        "section": "Preamble; all penalties attract GST at 18%",
        "page": 1,
    },
}
