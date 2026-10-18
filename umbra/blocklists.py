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
    # Analytics, crash-reporting, attribution and ad SDKs that many phone apps
    # embed. Each entry also covers its subdomains. Blocking them stops apps
    # reporting what you do in them; the apps themselves keep working, though
    # ads may not load and links that open an app through an attribution
    # service (Branch, AppsFlyer, Adjust) may land on a web page instead. Used
    # by every profile that sinkholes telemetry (an OS build bakes all lists into
    # one hosts file, so the lists cannot differ between those profiles).
    "mobile-trackers": [
        "firebase-settings.crashlytics.com",
        "crashlyticsreports-pa.googleapis.com",
        "googleads.g.doubleclick.net",
        "pagead2.googlesyndication.com",
        "adservice.google.com",
        "appsflyer.com",
        "adjust.com",
        "branch.io",
        "api.mixpanel.com",
        "api.amplitude.com",
        "api.segment.io",
        "ingest.sentry.io",
        "notify.bugsnag.com",
        "sessions.bugsnag.com",
        "applovin.com",
        "unityads.unity3d.com",
        "ads.mopub.com",
        "an.facebook.com",
    ],
}


def domains_for(list_names: list[str]) -> list[str]:
    """The sorted, de-duplicated union of the named blocklists."""
    out: list[str] = []
    for name in list_names:
        out.extend(TELEMETRY_BLOCKLISTS.get(name, []))
    return sorted(set(out))
