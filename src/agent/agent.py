from collections.abc import Sequence
from typing import Any


def respond(
    message: str, history: Sequence[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Return a deterministic placeholder response until the agent is implemented."""
    del history
    return {
        "answer": f"I heard you: {message}",
        "sources": {"sql": None, "policy_chunks": []},
    }
