"""Core-spec export tests — the language-neutral contract (pure, any OS)."""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from umbra import spec
from umbra.capabilities import ALL_CAPABILITIES
from umbra.platform import Platform
from umbra.profiles import list_profiles


def test_spec_validates_against_its_own_schema():
    doc = spec.build_spec()
    errors = list(Draft202012Validator(spec.build_schema()).iter_errors(doc))
    assert errors == [], [ (list(e.path), e.message) for e in errors ]


def test_spec_carries_every_platform_capability_and_profile():
    doc = spec.build_spec()
    assert set(doc["platforms"]) == {p.value for p in Platform}
    assert set(doc["capabilities"]) == set(ALL_CAPABILITIES)
    assert set(doc["profiles"]) == set(list_profiles())
    # every platform declares a level for every capability
    for p in Platform:
        assert set(doc["platforms"][p.value]["capabilities"]) == set(ALL_CAPABILITIES)


def test_spec_profiles_expose_required_capabilities():
    doc = spec.build_spec()
    # home's requires must round-trip into the spec (what the app scores against)
    assert set(doc["profiles"]["home"]["requires"]) <= set(ALL_CAPABILITIES)
    assert "firewall" in doc["profiles"]["home"]["requires"]


def test_enforcement_levels_are_complete_and_described():
    doc = spec.build_spec()
    names = {lvl["name"] for lvl in doc["enforcement_levels"]}
    assert names == {"enforced", "requires_entitlement", "requires_vpn_profile",
                     "requires_rooted_os", "advisory", "unavailable"}
    assert all(lvl["description"].strip() for lvl in doc["enforcement_levels"])


def test_write_spec_emits_two_valid_json_files(tmp_path):
    spec_path, schema_path = spec.write_spec(tmp_path / "spec")
    doc = json.loads(spec_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert doc["umbra_spec_version"] == spec.SPEC_VERSION
    assert list(Draft202012Validator(schema).iter_errors(doc)) == []


def _structural(doc: dict) -> dict:
    """Drop free-text (description/reason) so the freshness check guards STRUCTURE
    only. Prose is folded from YAML and reflows across PyYAML versions -- it must
    not gate CI. Levels, capability tokens, controls, profile requires and module
    config are what a code change alters, and those are compared exactly."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("description", "reason")}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    return strip(doc)


def test_checked_in_spec_is_structurally_up_to_date():
    # The committed spec/umbra-core.json must match the core's structure now, so a
    # capability/profile/enforcement change can't land without regenerating it.
    from umbra import paths
    root = paths._PKG_DIR.parent            # repo root (package's parent)
    committed = root / "spec" / "umbra-core.json"
    if not committed.exists():
        return  # not in a source checkout (e.g. installed wheel) -- nothing to compare
    on_disk = json.loads(committed.read_text(encoding="utf-8"))
    assert _structural(on_disk) == _structural(spec.build_spec()), \
        "spec/umbra-core.json is structurally stale; run: umbra export-spec"
