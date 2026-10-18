import json

from pricor.adapters.session_codec import decode, encode
from pricor.ports.question_model import Suggestion


def test_old_suggestion_without_memory_ids_loads_with_an_empty_list():
    document = json.loads(encode(Suggestion("yes", 0.8)))
    document["f"].pop("memory_ids")

    restored = decode(json.dumps(document))

    assert restored.memory_ids == []
