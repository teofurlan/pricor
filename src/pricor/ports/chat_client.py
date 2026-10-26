"""Port for structured chat clients."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatReply:
    content: dict[str, Any]
    latency_seconds: float


class ChatClient(Protocol):
    """A model-backed structured JSON chat client."""

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> ChatReply:
        """Send one chat turn and return the JSON object the model produced."""
        ...
