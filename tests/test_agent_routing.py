import json
import unittest
from pathlib import Path

from src.agent.agent import CUSTOMER_REFUSAL, respond


DATABASE = Path(__file__).resolve().parents[1] / "data" / "ridewise.db"


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
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


if __name__ == "__main__":
    unittest.main()
