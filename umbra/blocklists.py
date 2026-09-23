"""Telemetry blocklists — shared policy data, core (platform-agnostic).

These named lists of telemetry/tracker domains are the *policy* behind the
`telemetry` capability. The Linux agent sinkholes them via /etc/hosts; the mobile
adapters sinkhole them via a VPNService/Network-Extension DNS filter. So the data
lives here in the core and is exported in the spec (umbra export-spec), giving all
three platforms one blocklist instead of three that drift.

Curated, legible starter lists. A later phase can fetch a public blocklist; for
now these demonstrate the mechanism end to end.
"""

from __future__ import annotations

TELEMETRY_BLOCKLISTS: dict[str, list[str]] = {
    "os": [
        # Common OS/vendor telemetry endpoints (illustrative, edit freely).
        "incoming.telemetry.mozilla.org",
        "metrics.mozilla.org",
    ],
    "common-trackers": [
        "www.google-analytics.com",
        "analytics.google.com",
        "app-measurement.com",
        "graph.facebook.com",
    ],
}


def domains_for(list_names: list[str]) -> list[str]:
    """The sorted, de-duplicated union of the named blocklists."""
    out: list[str] = []
    for name in list_names:
        out.extend(TELEMETRY_BLOCKLISTS.get(name, []))
    return sorted(set(out))
