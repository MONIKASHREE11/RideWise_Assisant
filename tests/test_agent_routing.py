import copy
import json
import unittest
from pathlib import Path

from src.agent.agent import (
    CUSTOMER_REFUSAL,
    RETRIEVAL_FAILURE_REPLY,
    respond,
)
from src.db.safe_sql import AGENT_TABLES, CUSTOMER_TABLES, describe_allowed_views


DATABASE = Path(__file__).resolve().parents[1] / "data" / "ridewise.db"


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), copy.deepcopy(kwargs)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def function_call(name, arguments, call_id="call-1"):
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": call_id,
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ]
                }
            }
        ]
    }


def assistant_answer(answer):
    return {"choices": [{"message": {"content": answer}}]}


class AgentRoutingTests(unittest.TestCase):
    def test_customer_sql_is_run_through_scoped_database_view(self):
        fake_llm = FakeLLM(
            function_call("run_sql", {"sql": "SELECT customer_id FROM my_profile"}),
            assistant_answer("I found your profile."),
        )

        result = respond(
            "Show my profile",
            role="Customer",
            customer_id="CUST0001",
            db_path=DATABASE,
            llm=fake_llm,
        )

        self.assertEqual(result["answer"], "I found your profile.")
        self.assertEqual(
            result["sources"]["sql"],
            [
                "SELECT customer_id FROM my_profile",
                "SELECT customer_id FROM my_profile",
            ],
        )
        tool_result = fake_llm.calls[1][0][-1]["content"]
        self.assertEqual(json.loads(tool_result)["rows"], [{"customer_id": "CUST0001"}])

    def test_customer_other_customer_request_is_refused_before_llm(self):
        fake_llm = FakeLLM(assistant_answer("Should not be called"))

        result = respond(
            "Show booking data for CUST0002",
            role="Customer",
            customer_id="CUST0001",
            db_path=DATABASE,
            llm=fake_llm,
        )

        self.assertEqual(result["answer"], CUSTOMER_REFUSAL)
        self.assertEqual(fake_llm.calls, [])
        self.assertEqual(result["sources"], {"sql": [], "policy_chunks": []})

    def test_json_tool_call_fallback_when_endpoint_rejects_tools(self):
        unsupported = RuntimeError("tool calling is unsupported")
        unsupported.status_code = 400
        fake_llm = FakeLLM(
            unsupported,
            assistant_answer(
                json.dumps(
                    {
                        "tool": "run_sql",
                        "arguments": {"sql": "SELECT customer_id FROM my_profile"},
                    }
                )
            ),
            assistant_answer(json.dumps({"answer": "Your profile was retrieved."})),
        )

        result = respond(
            "Show my profile",
            role="Customer",
            customer_id="CUST0001",
            db_path=DATABASE,
            llm=fake_llm,
        )

        self.assertEqual(result["answer"], "Your profile was retrieved.")
        self.assertEqual(len(result["sources"]["sql"]), 2)
        self.assertEqual(fake_llm.calls[1][1], {})

    def test_schema_guidance_and_run_sql_tool_are_role_specific(self):
        for role, customer_id, allowed_views, denied_views in (
            ("Customer", "CUST0001", CUSTOMER_TABLES, AGENT_TABLES),
            ("Support Agent", None, AGENT_TABLES, CUSTOMER_TABLES),
        ):
            with self.subTest(role=role):
                fake_llm = FakeLLM(assistant_answer("Done."))
                result = respond(
                    "Hello",
                    role=role,
                    customer_id=customer_id,
                    db_path=DATABASE,
                    llm=fake_llm,
                )
                self.assertEqual(result["answer"], "Done.")
                messages, kwargs = fake_llm.calls[0]
                prompt = messages[0]["content"]
                sql_tool = next(
                    tool["function"]
                    for tool in kwargs["tools"]
                    if tool["function"]["name"] == "run_sql"
                )
                actual_views = describe_allowed_views(
                    DATABASE, role=role, customer_id=customer_id
                )
                for view_name in allowed_views:
                    self.assertIn(view_name, prompt)
                    self.assertIn(view_name, sql_tool["description"])
                    for column in actual_views[view_name]:
                        self.assertIn(column, prompt)
                        self.assertIn(column, sql_tool["description"])
                for view_name in denied_views:
                    self.assertNotIn(f"- {view_name}:", prompt)
                    self.assertNotIn(f"- {view_name}:", sql_tool["description"])
                self.assertIn("Base tables are never available", prompt)
                self.assertIn("Base tables are never available", sql_tool["description"])

    def test_support_prompt_requires_count_and_truthful_capped_list(self):
        fake_llm = FakeLLM(assistant_answer("Done."))
        respond(
            "Which payments are pending?",
            role="Support Agent",
            db_path=DATABASE,
            llm=fake_llm,
        )

        system_prompt = fake_llm.calls[0][0][0]["content"]
        for instruction in (
            "When a support query could return more than 10 rows",
            "COUNT(<id column>) query",
            "same permitted view with the same filter",
            "never use COUNT(*)",
            "state the true total",
            "only the first 10 rows are shown",
            "never describe a capped list as complete",
            "minimum customer-identifying detail",
            "Contact fields are masked and must remain masked",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, system_prompt)

    def test_customer_prompt_declines_operational_queries_without_support_rules(self):
        fake_llm = FakeLLM(assistant_answer("Done."))
        respond(
            "Hello",
            role="Customer",
            customer_id="CUST0010",
            db_path=DATABASE,
            llm=fake_llm,
        )

        system_prompt = fake_llm.calls[0][0][0]["content"]
        self.assertIn(
            "answer only about the signed-in customer's own bookings, payments, "
            "damage reports, and the policies",
            system_prompt,
        )
        self.assertIn(
            "That information is only available to support agents. I can help "
            "with your own account.",
            system_prompt,
        )
        self.assertIn("Always phrase results as 'in your account'", system_prompt)
        self.assertIn("never say 'in total' or 'across all'", system_prompt)
        self.assertIn(
            "I can only access your own account.",
            system_prompt,
        )
        self.assertNotIn("Count rows with COUNT(", system_prompt)
        self.assertNotIn("COUNT(<id column>)", system_prompt)
        for support_only_instruction in (
            "Support queries are capped at 10 rows",
            "COUNT(<id column>) query",
            "minimum customer-identifying detail",
            "Contact fields are masked and must remain masked",
        ):
            with self.subTest(instruction=support_only_instruction):
                self.assertNotIn(support_only_instruction, system_prompt)

    def test_prompt_requires_cancellation_policy_version_and_booking_date(self):
        fake_llm = FakeLLM(assistant_answer("Done."))
        respond(
            "I cancelled B-0005, what refund should I get?",
            role="Customer",
            customer_id="CUST0010",
            db_path=DATABASE,
            llm=fake_llm,
        )

        system_prompt = fake_llm.calls[0][0][0]["content"]
        self.assertIn(
            "Whenever an answer relies on a cancellation or refund "
            "calculation or policy chunk",
            system_prompt,
        )
        self.assertIn("state which policy version (v1 or v2) applied", system_prompt)
        self.assertIn("chosen by the booking date", system_prompt)

    def test_sql_error_is_retried_with_allowed_views_and_only_success_is_cited(self):
        fake_llm = FakeLLM(
            function_call(
                "run_sql",
                {"sql": "SELECT COUNT(booking_id) AS count FROM bookings"},
            ),
            function_call(
                "run_sql",
                {
                    "sql": "SELECT COUNT(booking_id) AS count FROM agent_bookings "
                    "WHERE booking_status = 'CNL_U'"
                },
            ),
            assistant_answer("There are 142 customer cancellations."),
        )

        result = respond(
            "How many bookings were cancelled by customers?",
            role="Support Agent",
            db_path=DATABASE,
            llm=fake_llm,
        )

        self.assertEqual(result["answer"], "There are 142 customer cancellations.")
        self.assertEqual(
            result["sources"]["sql"],
            [
                "SELECT COUNT(booking_id) AS count FROM agent_bookings "
                "WHERE booking_status = 'CNL_U'"
            ],
        )
        retry_feedback = json.loads(fake_llm.calls[1][0][-1]["content"])
        self.assertIn("agent_bookings", retry_feedback["error"])
        self.assertIn("Base tables are never available", retry_feedback["error"])
        rows = json.loads(fake_llm.calls[2][0][-1]["content"])["rows"]
        self.assertEqual(rows, [{"count": 142}])

    def test_final_no_record_answer_after_failed_sql_becomes_retrieval_fallback(self):
        fake_llm = FakeLLM(
            function_call(
                "run_sql",
                {"sql": "SELECT payment_id FROM payments WHERE payment_id='PAY00071'"},
            ),
            assistant_answer("No record found for that payment."),
        )

        result = respond(
            "Show the remark for PAY00071",
            role="Support Agent",
            db_path=DATABASE,
            llm=fake_llm,
        )

        self.assertEqual(result["answer"], RETRIEVAL_FAILURE_REPLY)
        self.assertNotIn("no record", result["answer"].casefold())
        self.assertEqual(result["sources"]["sql"], [])

    def test_json_tool_fallback_retries_failed_sql_before_final_answer(self):
        unsupported = RuntimeError("tool calling is unsupported")
        unsupported.status_code = 400
        fake_llm = FakeLLM(
            unsupported,
            assistant_answer(
                json.dumps(
                    {
                        "tool": "run_sql",
                        "arguments": {
                            "sql": "SELECT COUNT(booking_id) FROM bookings"
                        },
                    }
                )
            ),
            assistant_answer(
                json.dumps(
                    {
                        "tool": "run_sql",
                        "arguments": {
                            "sql": "SELECT COUNT(booking_id) AS count "
                            "FROM agent_bookings WHERE booking_status = 'CNL_U'"
                        },
                    }
                )
            ),
            assistant_answer(
                json.dumps({"answer": "There are 142 customer cancellations."})
            ),
        )

        result = respond(
            "How many bookings were cancelled by customers?",
            role="Support Agent",
            db_path=DATABASE,
            llm=fake_llm,
        )

        self.assertEqual(result["answer"], "There are 142 customer cancellations.")
        self.assertEqual(
            result["sources"]["sql"],
            [
                "SELECT COUNT(booking_id) AS count "
                "FROM agent_bookings WHERE booking_status = 'CNL_U'"
            ],
        )
        retry_feedback = json.loads(fake_llm.calls[2][0][-1]["content"])
        self.assertIn("agent_bookings", retry_feedback["tool_result"]["error"])


if __name__ == "__main__":
    unittest.main()
