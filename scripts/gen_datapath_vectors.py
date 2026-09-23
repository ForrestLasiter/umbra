#!/usr/bin/env python3
"""Generate golden datapath vectors: canonical DNS sinkhole query/response bytes.

These pin the exact wire bytes the sinkhole must produce for a blocked domain, so
the Python reference and the Kotlin/Swift ports are checked against ONE source of
truth in CI (byte-for-byte, not just "0.0.0.0 somewhere"). Regenerate after any
change to the DNS response format:

    python scripts/gen_datapath_vectors.py

Writes spec/datapath-vectors.json and copies it into the mobile test resources.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# --- the reference DNS builder (matches umbra's mobile DnsMessage ports) ------

def encode_query(name: str, qtype: int, ident: int = 0x1234) -> bytes:
    out = bytearray()
    def p16(v: int) -> None:
        out.extend([(v >> 8) & 0xFF, v & 0xFF])
    p16(ident); p16(0x0100); p16(1); p16(0); p16(0); p16(0)   # header, RD set
    for label in name.split("."):
        out.append(len(label)); out.extend(label.encode())
    out.append(0); p16(qtype); p16(1)                          # qtype, qclass=IN
    return bytes(out)


def blocked_response(payload: bytes) -> bytes:
    ident = (payload[0] << 8) | payload[1]
    flags = (payload[2] << 8) | payload[3]
    i = 12
    while i < len(payload):
        ln = payload[i]
        if ln == 0:
            i += 1; break
        i += 1 + ln
    qtype = (payload[i] << 8) | payload[i + 1]
    question_end = i + 4
    qlen = question_end - 12
    rdata = b"\x00\x00\x00\x00" if qtype == 1 else (b"\x00" * 16 if qtype == 28 else None)
    has = rdata is not None
    anc = 1 if has else 0
    rcode = 0 if has else 3
    answer_len = (12 + len(rdata)) if has else 0
    out = bytearray(12 + qlen + answer_len)

    def p16(o: int, v: int) -> None:
        out[o] = (v >> 8) & 0xFF; out[o + 1] = v & 0xFF

    p16(0, ident)
    p16(2, 0x8000 | (flags & 0x0100) | 0x0080 | rcode)
    p16(4, 1); p16(6, anc); p16(8, 0); p16(10, 0)
    out[12:12 + qlen] = payload[12:12 + qlen]
    if has:
        o = 12 + qlen
        p16(o, 0xC000 | 12); o += 2
        p16(o, qtype); o += 2
        p16(o, 1); o += 2
        p16(o, 0); p16(o + 2, 60); o += 4
        p16(o, len(rdata)); o += 2
        out[o:o + len(rdata)] = rdata
    return bytes(out)


CASES = [
    ("graph.facebook.com", 1),      # A     -> 0.0.0.0
    ("app-measurement.com", 1),     # A
    ("metrics.mozilla.org", 28),    # AAAA  -> ::
    ("analytics.google.com", 15),   # MX    -> NXDOMAIN
]


def build() -> dict:
    vectors = []
    for name, qtype in CASES:
        q = encode_query(name, qtype)
        r = blocked_response(q)
        vectors.append({"name": name, "qtype": qtype,
                        "query_hex": q.hex(), "response_hex": r.hex()})
    return {"version": 1, "dns_blocked_responses": vectors}


def main() -> None:
    doc = build()
    text = json.dumps(doc, indent=2) + "\n"
    targets = [
        ROOT / "spec" / "datapath-vectors.json",
        ROOT / "android" / "app" / "src" / "test" / "resources" / "datapath-vectors.json",
        ROOT / "ios" / "UmbraCore" / "Tests" / "UmbraCoreTests" / "datapath-vectors.json",
    ]
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
        print(f"wrote {t.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
