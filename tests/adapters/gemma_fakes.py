from pricor.adapters.ollama_client import ChatReply


class FakeClient:
    """Stands in for OllamaClient: returns a canned reply or raises a canned error."""

    def __init__(self, content=None, error=None, latency=0.25):
        self.content = content
        self.error = error
        self.latency = latency
        self.calls = []

    def chat_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise self.error
        return ChatReply(self.content, self.latency)
