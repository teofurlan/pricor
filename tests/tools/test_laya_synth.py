import re
from collections import Counter

import pytest

from pricor.domain.roles import ColumnRole
from tools.laya.split import normalize_header
from tools.laya.synth import generate_columns

BANNED = frozenset({"codigo", "descripcion", "preciolista", "precioventa", "preciosugerido", "marca", "rubro"})


def columns(n=300, seed=7, banned=BANNED, **kwargs):
    return generate_columns(n, seed, banned, **kwargs)


def test_generation_is_deterministic_for_a_seed_and_differs_between_seeds():
    assert columns(60, seed=1) == columns(60, seed=1)
    assert columns(60, seed=1) != columns(60, seed=2)


def test_every_role_is_represented_in_a_balanced_way():
    counts = Counter(column.role for column in columns(300))

    assert set(counts) == set(ColumnRole)
    assert max(counts.values()) - min(counts.values()) <= 1


def test_banned_headers_never_appear_in_any_spelling():
    for column in columns(600, seed=3):
        assert normalize_header(column.header) not in BANNED, column.header


def test_the_banned_headers_are_really_in_the_vocabulary_otherwise_the_test_proves_nothing():
    unbanned = {normalize_header(c.header) for c in columns(900, seed=3, banned=frozenset())}

    assert {"codigo", "descripcion", "preciolista", "precioventa"} <= unbanned


def test_some_columns_have_no_header_and_they_cover_the_main_roles():
    headerless = [c for c in columns(600) if c.header == ""]

    assert 0.05 < len(headerless) / 600 < 0.25
    assert {ColumnRole.CODE, ColumnRole.DESCRIPTION, ColumnRole.COST_PRICE} <= {c.role for c in headerless}


def test_compact_header_forms_are_in_the_vocabulary():
    seen = {normalize_header(c.header) for c in columns(900, seed=5, banned=frozenset())}

    assert {"codart", "cantxbulto", "precio1"} <= seen


def test_cost_and_retail_headers_carry_different_modifiers():
    seen = columns(900, seed=5, banned=frozenset())
    cost = {normalize_header(c.header) for c in seen if c.role is ColumnRole.COST_PRICE} - {""}
    retail = {normalize_header(c.header) for c in seen if c.role is ColumnRole.RETAIL_PRICE} - {""}

    assert cost and retail and not cost & retail
    assert any("costo" in h or "lista" in h or "neto" in h for h in cost)
    assert any("pvp" in h or "publico" in h or "sugerido" in h for h in retail)


def test_values_look_like_their_role():
    by_role = {}
    for column in columns(300, seed=11):
        by_role.setdefault(column.role, []).append(column)

    assert all(re.fullmatch(r"\d{13}", v) for c in by_role[ColumnRole.BARCODE] for v in c.values if v)
    assert any("%" in v for c in by_role[ColumnRole.VAT_RATE] for v in c.values) or any(
        v in ("21", "10,5", "10.5") for c in by_role[ColumnRole.VAT_RATE] for v in c.values
    )
    currency_values = {v for c in by_role[ColumnRole.CURRENCY] for v in c.values}
    assert {"$", "u$s"} & currency_values
    assert all(len(c.values) >= 10 for c in columns(30))


def test_the_ignore_role_includes_empty_columns():
    assert any(not any(c.values) for c in columns(300, seed=2) if c.role is ColumnRole.IGNORE)


def test_a_banned_set_that_empties_a_role_is_an_error():
    everything = frozenset(normalize_header(c.header) for c in columns(900, seed=1, banned=frozenset()))
    with pytest.raises(ValueError):
        columns(10, banned=everything - {""})
