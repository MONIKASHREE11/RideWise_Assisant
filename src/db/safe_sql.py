from __future__ import annotations

import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


CUSTOMER_ID_PATTERN = re.compile(r"CUST[0-9]{4}\Z")
CUSTOMER_TABLES = frozenset(
    {"my_profile", "my_bookings", "my_payments", "my_damage_reports"}
)
AGENT_TABLES = frozenset(
    {
        "agent_customers",
        "agent_vehicles",
        "agent_bookings",
        "agent_payments",
        "agent_damage_reports",
    }
)
SOURCE_TABLES = frozenset(
    {"customers", "vehicles", "bookings", "payments", "damage_reports"}
)
DEFAULT_ROW_LIMIT = 25
MAX_ROW_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 2.0
_EMAIL_PATTERN = re.compile(
    r"(?i)(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w-])"
)
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?91[\s().-]?)?[6-9](?:[\s().-]?\d){9}(?!\d)")
_SAFE_FUNCTIONS = frozenset(
    {
        "abs",
        "avg",
        "coalesce",
        "count",
        "date",
        "datetime",
        "ifnull",
        "instr",
        "julianday",
        "length",
        "lower",
        "max",
        "min",
        "nullif",
        "round",
        "sanitize_untrusted_text",
        "strftime",
        "substr",
        "sum",
        "time",
        "total",
        "upper",
    }
)
_FORBIDDEN_SQL_WORDS = re.compile(
    r"\b(?:attach|detach|pragma|vacuum|insert|update|delete|replace|"
    r"create|drop|alter|reindex|analyze|begin|commit|rollback|savepoint|"
    r"release|load_extension)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryResult:
    sql: str
    rows: list[dict[str, Any]]
    truncated: bool


def validate_select(sql: str) -> str:
    """Accept a single SELECT statement without comments or chained SQL."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("A non-empty SELECT statement is required.")

    statement = sql.strip()
    if "--" in statement or "/*" in statement or "*/" in statement:
        raise ValueError("SQL comments are not allowed.")
    if ";" in statement.rstrip(";"):
        raise ValueError("Only one SQL statement is allowed.")
    statement = statement.rstrip(";").strip()
    if not re.match(r"(?is)^select\b", statement):
        raise ValueError("Only SELECT statements are allowed.")
    if _FORBIDDEN_SQL_WORDS.search(statement):
        raise ValueError("The SQL contains a forbidden operation.")
    return statement


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _validate_customer(connection: sqlite3.Connection, customer_id: str) -> None:
    if not CUSTOMER_ID_PATTERN.fullmatch(customer_id):
        raise ValueError("Customer ID must match CUST followed by four digits.")
    exists = connection.execute(
        "SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if exists is None:
        raise ValueError("Customer ID was not found.")


def _install_customer_views(
    connection: sqlite3.Connection, customer_id: str
) -> None:
    connection.execute(
        f"""
        CREATE TEMP VIEW my_profile AS
        SELECT customer_id, full_name, phone, email, city, date_of_birth,
               kyc_status, customer_tier, created_at
        FROM customers
        WHERE customer_id = '{customer_id}'
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW my_bookings AS
        SELECT b.*, v.vehicle_type, v.model AS vehicle_model, v.hub_name
        FROM bookings AS b
        JOIN vehicles AS v ON v.vehicle_id = b.vehicle_id
        WHERE b.customer_id = '{customer_id}'
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW my_payments AS
        SELECT p.payment_id, p.booking_id, p.payment_type, p.amount,
               p.gst_amount, p.payment_method, p.payment_status, p.paid_at
        FROM payments AS p
        JOIN bookings AS b ON b.booking_id = p.booking_id
        WHERE b.customer_id = '{customer_id}'
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW my_damage_reports AS
        SELECT d.report_id, d.booking_id, d.vehicle_id, d.reported_by,
               d.damage_category, d.severity, d.assessed_cost,
               d.claim_status, d.reported_at
        FROM damage_reports AS d
        JOIN bookings AS b ON b.booking_id = d.booking_id
        WHERE b.customer_id = '{customer_id}'
        """
    )


def _mask_untrusted_text(value: str | None, customer_names: tuple[str, ...]) -> str | None:
    if value is None:
        return None

    redactions: list[str] = []

    def preserve_redaction(match: re.Match[str], label: str) -> str:
        redactions.append(f"[{label} redacted]")
        return f"__RIDEWISE_REDACTION_{len(redactions) - 1}__"

    sanitized = _EMAIL_PATTERN.sub(
        lambda match: preserve_redaction(match, "email"), value
    )
    sanitized = _PHONE_PATTERN.sub(
        lambda match: preserve_redaction(match, "phone"), sanitized
    )
    name_tokens = {
        token
        for name in customer_names
        for token in re.findall(r"[^\W_]+", name, flags=re.UNICODE)
    }
    for token in sorted(name_tokens, key=len, reverse=True):
        sanitized = re.sub(
            rf"(?i)(?<!\w){re.escape(token)}(?!\w)",
            "[name redacted]",
            sanitized,
        )
    for index, redaction in enumerate(redactions):
        sanitized = sanitized.replace(f"__RIDEWISE_REDACTION_{index}__", redaction)
    return sanitized


def _install_agent_views(connection: sqlite3.Connection) -> None:
    customer_names = tuple(
        row[0]
        for row in connection.execute(
            "SELECT full_name FROM customers WHERE full_name IS NOT NULL"
        ).fetchall()
        if row[0].strip()
    )
    connection.create_function(
        "sanitize_untrusted_text",
        1,
        lambda value: _mask_untrusted_text(value, customer_names),
        deterministic=True,
    )
    connection.executescript(
        """
        CREATE TEMP VIEW agent_customers AS
        SELECT customer_id, full_name,
               CASE WHEN phone IS NULL THEN NULL
                    ELSE '******' || substr(phone, -4) END AS phone,
               CASE WHEN email IS NULL THEN NULL
                    WHEN instr(email, '@') > 1
                    THEN substr(email, 1, 1) || '***' ||
                         substr(email, instr(email, '@'))
                    ELSE '***' END AS email,
               city, date_of_birth, kyc_status, customer_tier, created_at
        FROM customers;
        CREATE TEMP VIEW agent_vehicles AS SELECT * FROM vehicles;
        CREATE TEMP VIEW agent_bookings AS SELECT * FROM bookings;
        CREATE TEMP VIEW agent_payments AS
        SELECT payment_id, booking_id, payment_type, amount, gst_amount,
               payment_method, payment_status, transaction_ref, paid_at,
               sanitize_untrusted_text(remarks) AS remarks
        FROM payments;
        CREATE TEMP VIEW agent_damage_reports AS
        SELECT report_id, booking_id, vehicle_id, reported_by, damage_category,
               severity, sanitize_untrusted_text(description) AS description,
               assessed_cost, claim_status, reported_at
        FROM damage_reports;
        """
    )


@contextmanager
def readonly_connection(
    db_path: str | Path,
    *,
    role: str,
    customer_id: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[sqlite3.Connection]:
    """Open a read-only DB connection with views and role-based read access."""
    normalized_role = role.strip().casefold()
    if normalized_role not in {"customer", "support agent"}:
        raise ValueError("Role must be 'Customer' or 'Support Agent'.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")

    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
    try:
        if normalized_role == "customer":
            if customer_id is None:
                raise ValueError("A customer ID is required for customer access.")
            _validate_customer(connection, customer_id)
            _install_customer_views(connection, customer_id)
            allowed_views = CUSTOMER_TABLES
        else:
            _install_agent_views(connection)
            allowed_views = AGENT_TABLES

        def authorize(
            action: int,
            arg1: str | None,
            arg2: str | None,
            database_name: str | None,
            source: str | None,
        ) -> int:
            del database_name
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                table_name = (arg1 or "").casefold()
                view_source = (source or "").casefold()
                if table_name in allowed_views:
                    return sqlite3.SQLITE_OK
                if table_name in SOURCE_TABLES and view_source in allowed_views:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION:
                function_name = (arg2 or arg1 or "").casefold()
                return (
                    sqlite3.SQLITE_OK
                    if function_name in _SAFE_FUNCTIONS
                    else sqlite3.SQLITE_DENY
                )
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        deadline = time.monotonic() + timeout_seconds
        connection.set_progress_handler(
            lambda: int(time.monotonic() >= deadline), 1000
        )
        yield connection
    finally:
        connection.close()


def execute_select(
    sql: str,
    db_path: str | Path,
    *,
    role: str,
    customer_id: str | None = None,
    row_limit: int = DEFAULT_ROW_LIMIT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> QueryResult:
    """Run a validated, authorized SELECT and return at most row_limit rows."""
    statement = validate_select(sql)
    if not 1 <= row_limit <= MAX_ROW_LIMIT:
        raise ValueError(f"row_limit must be between 1 and {MAX_ROW_LIMIT}.")

    bounded_sql = (
        f"SELECT * FROM ({statement}) AS _ridewise_result LIMIT {row_limit + 1}"
    )
    with readonly_connection(
        db_path,
        role=role,
        customer_id=customer_id,
        timeout_seconds=timeout_seconds,
    ) as connection:
        cursor = connection.execute(bounded_sql)
        columns = [column[0] for column in cursor.description or ()]
        fetched = cursor.fetchmany(row_limit + 1)

    truncated = len(fetched) > row_limit
    rows = [dict(zip(columns, row)) for row in fetched[:row_limit]]
    return QueryResult(sql=statement, rows=rows, truncated=truncated)
