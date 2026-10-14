import pytest

from pricor.adapters.dolarapi_provider import DolarApiProvider
from pricor.entrypoints.wiring import dependencies_from_env


def deps(tmp_path, **env):
    return dependencies_from_env({"PRICOR_DB": str(tmp_path / "pricor.db"), **env})


def test_the_live_rate_source_is_wired_with_the_official_rate_as_default_setting(tmp_path):
    use_case = deps(tmp_path).use_case

    assert isinstance(use_case._fx, DolarApiProvider)
    assert use_case._default_fx_rate_type == "oficial"


def test_the_default_rate_type_is_a_setting(tmp_path):
    assert deps(tmp_path, PRICOR_FX_RATE_TYPE="blue").use_case._default_fx_rate_type == "blue"


@pytest.mark.parametrize("value", ["paralelo", "manual", ""])
def test_an_unknown_default_rate_type_is_refused_at_startup(tmp_path, value):
    with pytest.raises(ValueError, match="PRICOR_FX_RATE_TYPE"):
        deps(tmp_path, PRICOR_FX_RATE_TYPE=value)
