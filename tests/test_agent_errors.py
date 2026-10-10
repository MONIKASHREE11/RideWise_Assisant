import sqlite3
import unittest
from unittest.mock import patch

from src.agent.agent import DATABASE_ERROR_REPLY, respond_safely


class AgentDatabaseErrorTests(unittest.TestCase):
    @patch("src.agent.agent.respond")
    def test_database_error_returns_friendly_message_without_sql_details(
        self, mock_respond
    ) -> None:
        raw_error = "no such column: payments.remarks; SELECT secret"
        mock_respond.side_effect = sqlite3.OperationalError(raw_error)

        result = respond_safely("Show my payment notes")

        self.assertEqual(result["answer"], DATABASE_ERROR_REPLY)
        self.assertNotIn(raw_error, result["answer"])
        self.assertEqual(result["sources"], {"sql": [], "policy_chunks": []})

    @patch("src.agent.agent.respond")
    def test_model_errors_return_friendly_fallback(self, mock_respond) -> None:
        mock_respond.side_effect = TimeoutError("provider timeout secret")

        result = respond_safely("Show my booking")

        self.assertIn("temporarily unavailable", result["answer"])
        self.assertNotIn("provider timeout", result["answer"])


if __name__ == "__main__":
    unittest.main()
