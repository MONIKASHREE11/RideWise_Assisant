from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


def _required_setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return value


def create_client() -> OpenAI:
    """Create the NeoStats OpenAI-compatible client from environment settings."""
    load_dotenv()
    return OpenAI(
        base_url=_required_setting("NEOSTATS_BASE_URL"),
        api_key=_required_setting("NEOSTATS_API_KEY"),
        timeout=15.0,
        max_retries=1,
    )


def get_model() -> str:
    load_dotenv()
    return _required_setting("NEOSTATS_MODEL")


def get_embedding_model() -> str | None:
    load_dotenv()
    model = os.getenv("NEOSTATS_EMBEDDING_MODEL", "").strip()
    if not model:
        return None
    if not os.getenv("NEOSTATS_BASE_URL", "").strip():
        return None
    if not os.getenv("NEOSTATS_API_KEY", "").strip():
        return None
    return model


def chat_completion(
    messages: Iterable[dict[str, Any]],
    *,
    temperature: float = 0.0,
) -> Any:
    """Request one chat completion using the configured NeoStats deployment."""
    return create_client().chat.completions.create(
        model=get_model(),
        messages=list(messages),
        temperature=temperature,
    )
