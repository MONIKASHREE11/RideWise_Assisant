import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db.safe_sql import execute_select, validate_select


class SafeSqlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        connection = sqlite3.connect(self.db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE customers (
                    customer_id TEXT PRIMARY KEY,
                    full_name TEXT,
                    phone TEXT,
                    email TEXT,
                    city TEXT,
                    date_of_birth TEXT,
                    driving_license_no TEXT,
                    kyc_status TEXT,
                    customer_tier TEXT,
                    created_at TEXT
                );
                CREATE TABLE vehicles (
                    vehicle_id TEXT PRIMARY KEY,
                    vehicle_type TEXT,
                    model TEXT,
                    hub_name TEXT
                );
                CREATE TABLE bookings (
                    booking_id TEXT PRIMARY KEY,
                    customer_id TEXT,
                    vehicle_id TEXT,
                    booking_status TEXT
                );
                CREATE TABLE payments (
                    payment_id TEXT PRIMARY KEY,
                    booking_id TEXT,
                    amount REAL,
                    remarks TEXT
                );
                CREATE TABLE damage_reports (
                    report_id TEXT PRIMARY KEY,
                    booking_id TEXT,
                    description TEXT
                );
                INSERT INTO customers VALUES (
                    'CUST0001', 'Ada', '9876543210', 'ada@example.com',
                    'Bengaluru', '1990-01-01', 'DL-ADA-PRIVATE', 'VERIFIED',
                    'GOLD', '2026-01-01 00:00:00'
                );
                INSERT INTO customers VALUES (
                    'CUST0002', 'Lin', '9123456780', 'lin@example.com',
                    'Mysuru', '1991-02-02', 'DL-LIN-PRIVATE', 'VERIFIED',
                    'STANDARD', '2026-01-02 00:00:00'
                );
                INSERT INTO vehicles VALUES ('VEH001', 'BIKE', 'City Bike', 'Hub A');
                INSERT INTO bookings VALUES ('B-0001', 'CUST0001', 'VEH001', 'CMP');
                INSERT INTO bookings VALUES ('B-0002', 'CUST0002', 'VEH001', 'CMP');
                INSERT INTO payments VALUES ('PAY00001', 'B-0001', 100.0, 'first');
                INSERT INTO payments VALUES ('PAY00002', 'B-0002', 200.0, 'second');
                INSERT INTO damage_reports VALUES ('DMG0001', 'B-0001', 'scratch');
                INSERT INTO damage_reports VALUES ('DMG0002', 'B-0002', 'dent');
                """
            )
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_customer_query(self, sql: str):
        return execute_select(
            sql,
            self.db_path,
            role="Customer",
            customer_id="CUST0001",
        )

    def test_customer_views_are_scoped_through_bookings(self) -> None:
        cases = (
            ("SELECT customer_id FROM my_profile", [{"customer_id": "CUST0001"}]),
            ("SELECT booking_id FROM my_bookings", [{"booking_id": "B-0001"}]),
            ("SELECT payment_id FROM my_payments", [{"payment_id": "PAY00001"}]),
            (
                "SELECT report_id FROM my_damage_reports",
                [{"report_id": "DMG0001"}],
            ),
        )
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertEqual(self.run_customer_query(sql).rows, expected)

    def test_customer_cannot_read_base_tables_or_union_with_them(self) -> None:
        for table in ("customers", "bookings", "payments", "damage_reports"):
            with self.subTest(table=table), self.assertRaises(sqlite3.DatabaseError):
                self.run_customer_query(f"SELECT * FROM {table}")
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_customer_query("SELECT name FROM sqlite_master")
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_customer_query(
                "SELECT booking_id FROM my_bookings "
                "UNION SELECT booking_id FROM bookings"
            )

    def test_customer_scoped_views_return_no_other_customers_rows(self) -> None:
        profile = self.run_customer_query(
            "SELECT customer_id FROM my_profile "
            "WHERE customer_id = 'CUST0002'"
        )
        bookings = self.run_customer_query(
            "SELECT * FROM my_bookings "
            "WHERE customer_id <> 'CUST0001'"
        )
        self.assertEqual(profile.rows, [])
        self.assertEqual(bookings.rows, [])

    def test_customer_cannot_use_union_or_subquery_to_escape_views(self) -> None:
        queries = (
            "SELECT customer_id FROM my_profile "
            "UNION SELECT customer_id FROM customers",
            "SELECT customer_id FROM "
            "(SELECT customer_id FROM customers)",
        )
        for sql in queries:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                self.run_customer_query(sql)

    def test_customer_cannot_read_sqlite_master_or_use_pragma(self) -> None:
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_customer_query("SELECT name FROM sqlite_master")
        with self.assertRaises(ValueError):
            self.run_customer_query("PRAGMA table_info(customers)")

    def test_customer_id_format_and_existence_are_validated(self) -> None:
        for invalid_id, message in (
            ("c1", "must match CUST followed by four digits"),
            ("CUST9999", "not found"),
        ):
            with self.subTest(customer_id=invalid_id):
                with self.assertRaisesRegex(ValueError, message):
                    execute_select(
                        "SELECT customer_id FROM my_profile",
                        self.db_path,
                        role="Customer",
                        customer_id=invalid_id,
                    )

    def test_support_uses_masked_customer_view_without_license(self) -> None:
        result = execute_select(
            "SELECT customer_id, phone, email FROM agent_customers",
            self.db_path,
            role="Support Agent",
        )
        self.assertEqual(
            result.rows[0],
            {
                "customer_id": "CUST0001",
                "phone": "******3210",
                "email": "a***@example.com",
            },
        )
        with self.assertRaises(sqlite3.DatabaseError):
            execute_select(
                "SELECT driving_license_no FROM agent_customers",
                self.db_path,
                role="Support Agent",
            )

    def test_support_cannot_bypass_masked_view_or_read_schema(self) -> None:
        for sql in (
            "SELECT phone FROM customers",
            "SELECT name FROM sqlite_master",
            "SELECT phone FROM "
            "(SELECT phone FROM customers)",
            "SELECT phone FROM agent_customers UNION SELECT phone FROM customers",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                execute_select(sql, self.db_path, role="Support Agent")

    def test_dangerous_sql_forms_are_rejected(self) -> None:
        queries = (
            "",
            "SELECT 1; SELECT 2",
            "SELECT 1; DELETE FROM bookings",
            "SELECT 1 -- comment",
            "SELECT /* comment */ 1",
            "ATTACH DATABASE 'other.db' AS other",
            "PRAGMA table_info(customers)",
        )
        for sql in queries:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_select(sql)

    def test_read_only_connection_and_row_limit(self) -> None:
        with self.assertRaises(ValueError):
            execute_select(
                "SELECT * FROM agent_bookings",
                self.db_path,
                role="Support Agent",
                row_limit=0,
            )
        result = execute_select(
            "SELECT booking_id FROM agent_bookings",
            self.db_path,
            role="Support Agent",
            row_limit=1,
        )
        self.assertEqual(len(result.rows), 1)
        self.assertTrue(result.truncated)


if __name__ == "__main__":
    unittest.main()
