"""Port for structured chat clients."""

from collections.abc import Sequence
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


class VisionChatClient(Protocol):
    """A multimodal chat client that accepts PNG page images alongside a JSON schema."""

    def chat_json_with_images(
        self,
        system: str,
        user: str,
        images: Sequence[bytes],
        schema: dict[str, Any],
    ) -> ChatReply:
        """Send one chat turn with PNG image bytes and return the parsed JSON object."""
        ...
