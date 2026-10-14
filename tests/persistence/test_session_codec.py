import json
from decimal import Decimal

import pytest

from pricor.adapters.session_codec import SessionCodecError, decode, encode

from .sessions import Flow


def stages():
    flow = Flow()
    return {
        "header_choice_required": flow.headerless(),
        "questions_pending": flow.start(),
        "ready_for_preview": flow.ready(),
        "approved": Flow().approved(),
    }


@pytest.mark.parametrize("stage", ["header_choice_required", "questions_pending", "ready_for_preview", "approved"])
def test_every_stage_of_a_session_round_trips_exactly(stage):
    session = stages()[stage]
    restored = decode(encode(session))
    assert restored == session
    assert repr(restored) == repr(session)  # Decimal exponents, tuple/list kinds, enum members
    assert restored.status is session.status


def test_decimals_keep_their_digits():
    values = [Decimal("855.00"), Decimal("0.1"), Decimal("1E+2"), Decimal("-0.000")]
    restored = decode(encode(values))
    assert [str(value) for value in restored] == ["855.00", "0.1", "1E+2", "-0.000"]


def test_dicts_with_non_string_keys_and_reserved_looking_keys_survive():
    data = {1: "a", "$t": "not a tag", "k": (1, [2, (3,)])}
    assert decode(encode(data)) == data


def test_encoded_form_is_json():
    json.loads(encode(Flow().approved()))


@pytest.mark.parametrize(
    "payload",
    [
        '{"$t": "dc", "c": "os.path", "f": []}',
        '{"$t": "dc", "c": "pricor.domain.plan.Nope", "f": []}',
        '{"$t": "dc", "c": "builtins.dict", "f": []}',
        '{"$t": "mystery"}',
        "not json",
    ],
)
def test_untrusted_or_corrupt_payloads_are_refused(payload):
    with pytest.raises(SessionCodecError):
        decode(payload)


def test_a_reuse_session_round_trips_with_its_change_list():
    from dataclasses import replace

    from pricor.ports.import_session import PlanChange

    session = replace(
        Flow().start(),
        mode="reuse",
        based_on_plan_version=2,
        changes=(PlanChange("moved", "codigo", 0, 1, "code", "code", role="code"),),
    )

    restored = decode(encode(session))

    assert restored == session
    assert restored.changes[0].role == "code"


def test_a_session_stored_before_reuse_existed_still_loads():
    document = json.loads(encode(Flow().start()))
    for name in ("mode", "based_on_plan_version", "changes"):
        document["f"].pop(name)

    restored = decode(json.dumps(document))

    assert (restored.mode, restored.based_on_plan_version, restored.changes) == (
        "first_import",
        None,
        (),
    )
