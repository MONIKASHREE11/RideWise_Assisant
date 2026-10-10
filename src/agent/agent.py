import logging
import sqlite3
from collections.abc import Sequence
from typing import Any


_LOGGER = logging.getLogger(__name__)
DATABASE_ERROR_REPLY = (
    "I couldn't safely retrieve that information. Please try again."
)


def respond(
    message: str, history: Sequence[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Return a deterministic placeholder response until the agent is implemented."""
    del history
    return {
        "answer": f"I heard you: {message}",
        "sources": {"sql": None, "policy_chunks": []},
    }


def respond_safely(
    message: str, history: Sequence[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Replace database exceptions with a short user-safe response."""
    try:
        return respond(message, history=history)
    except sqlite3.DatabaseError:
        _LOGGER.exception("Database query failed while handling a chat request")
        return {
            "answer": DATABASE_ERROR_REPLY,
            "sources": {"sql": None, "policy_chunks": []},
        }
