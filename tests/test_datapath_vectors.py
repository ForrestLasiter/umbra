"""Golden datapath vectors: the canonical DNS-sinkhole bytes, checked in CI.

Proves the committed vectors are correct against the reference builder, and that
the copies the Kotlin/Swift test suites load are byte-identical to the canonical
one -- so all three implementations are pinned to the same wire bytes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_generator():
    path = ROOT / "scripts" / "gen_datapath_vectors.py"
    spec = importlib.util.spec_from_file_location("gen_datapath_vectors", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_generator()

CANONICAL = ROOT / "spec" / "datapath-vectors.json"
COPIES = [
    ROOT / "android" / "app" / "src" / "test" / "resources" / "datapath-vectors.json",
    ROOT / "ios" / "UmbraCore" / "Tests" / "UmbraCoreTests" / "datapath-vectors.json",
]


def test_committed_vectors_match_the_reference_builder():
    on_disk = json.loads(CANONICAL.read_text(encoding="utf-8"))
    assert on_disk == gen.build(), "spec/datapath-vectors.json is stale; run scripts/gen_datapath_vectors.py"


def test_each_response_is_what_the_builder_produces():
    doc = json.loads(CANONICAL.read_text(encoding="utf-8"))
    for v in doc["dns_blocked_responses"]:
        query = bytes.fromhex(v["query_hex"])
        assert gen.blocked_response(query).hex() == v["response_hex"], v["name"]


def test_a_record_vectors_sinkhole_to_zero():
    doc = json.loads(CANONICAL.read_text(encoding="utf-8"))
    for v in doc["dns_blocked_responses"]:
        if v["qtype"] == 1:                       # A -> last 4 bytes are 0.0.0.0
            assert bytes.fromhex(v["response_hex"])[-4:] == b"\x00\x00\x00\x00"


def test_blocklist_cases_match_the_reference_matcher():
    doc = json.loads(CANONICAL.read_text(encoding="utf-8"))
    domains = doc["blocklist"]["domains"]
    for c in doc["blocklist"]["cases"]:
        assert gen.is_blocked(domains, c["name"]) == c["blocked"], c["name"]


def test_mobile_copies_are_byte_identical():
    canonical = CANONICAL.read_text(encoding="utf-8")
    for copy in COPIES:
        assert copy.exists(), f"missing vector copy: {copy}"
        assert copy.read_text(encoding="utf-8") == canonical, \
            f"{copy} drifted; run scripts/gen_datapath_vectors.py"
