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

from umbra.blocklist_stalkerware import STALKERWARE_SERVERS

TELEMETRY_BLOCKLISTS: dict[str, list[str]] = {
    "os": [
        # Common OS/vendor telemetry endpoints (illustrative, edit freely).
        "incoming.telemetry.mozilla.org",
        "metrics.mozilla.org",
        "mobile.events.data.microsoft.com",
        "self.events.data.microsoft.com",
        "vortex.data.microsoft.com",
    ],
    "common-trackers": [
        "www.google-analytics.com",
        "analytics.google.com",
        "app-measurement.com",
        "region1.app-measurement.com",
        "ssl.google-analytics.com",
        "stats.g.doubleclick.net",
        "graph.facebook.com",
    ],
    # Analytics, crash-reporting, attribution and ad SDKs that many phone apps
    # embed. Blocking them stops apps reporting what you do in them; the apps
    # themselves keep working, though ads may not load and links that open an
    # app through an attribution service (Branch, AppsFlyer, Adjust) may land on
    # a web page instead. Used by every profile that sinkholes telemetry (an OS
    # build bakes all lists into one hosts file, so the lists cannot differ
    # between those profiles).
    #
    # Matching differs by platform: the Android app's DNS filter and Linux's
    # resolver-level sinkhole treat an entry as covering its subdomains, but an
    # Android OS build's hosts file matches exact names only. So the hosts each
    # SDK actually contacts are listed by name too; entries whose real hosts are
    # random per customer (Sentry's oNNN.ingest.sentry.io) are effective only
    # through the app's filter.
    "mobile-trackers": [
        # Crash reporting
        "firebase-settings.crashlytics.com",
        "crashlyticsreports-pa.googleapis.com",
        "ingest.sentry.io",
        "notify.bugsnag.com",
        "sessions.bugsnag.com",
        "settings.crashlytics.com",
        "in.appcenter.ms",
        "mobile-collector.newrelic.com",
        "android.bugly.qq.com",
        # Google ads
        "googleads.g.doubleclick.net",
        "pagead2.googlesyndication.com",
        "adservice.google.com",
        # Attribution
        "appsflyer.com",
        "t.appsflyer.com",
        "inapps.appsflyer.com",
        "launches.appsflyer.com",
        "conversions.appsflyer.com",
        "register.appsflyer.com",
        "appsflyersdk.com",
        "launches.appsflyersdk.com",
        "inapps.appsflyersdk.com",
        "conversions.appsflyersdk.com",
        "gcdsdk.appsflyersdk.com",
        "adjust.com",
        "app.adjust.com",
        "s2s.adjust.com",
        "gdpr.adjust.com",
        "subscription.adjust.com",
        "control.kochava.com",
        "sdk-api-v1.singular.net",
        "branch.io",
        "api.branch.io",
        "api2.branch.io",
        "api3.branch.io",
        # Product analytics
        "api.mixpanel.com",
        "api-js.mixpanel.com",
        "decide.mixpanel.com",
        "api.amplitude.com",
        "api2.amplitude.com",
        "api.segment.io",
        "cdn.segment.com",
        "data.flurry.com",
        "startup.mobile.yandex.net",
        "report.appmetrica.yandex.net",
        "ulogs.umeng.com",
        # Ad networks
        "applovin.com",
        "a.applovin.com",
        "d.applovin.com",
        "ms.applovin.com",
        "rt.applovin.com",
        "prod-a.applovin.com",
        "prod-ms.applovin.com",
        "unityads.unity3d.com",
        "auction.unityads.unity3d.com",
        "config.unityads.unity3d.com",
        "publisher-config.unityads.unity3d.com",
        "ads.mopub.com",
        "an.facebook.com",
        "live.chartboost.com",
        "z.moatads.com",
    ],
    # Servers that known stalkerware reports to (Echap's stalkerware-indicators,
    # CC-BY 4.0; see umbra/blocklist_stalkerware.py). Exact names, so they work
    # the same on every platform.
    "stalkerware": STALKERWARE_SERVERS,
}


def domains_for(list_names: list[str]) -> list[str]:
    """The sorted, de-duplicated union of the named blocklists."""
    out: list[str] = []
    for name in list_names:
        out.extend(TELEMETRY_BLOCKLISTS.get(name, []))
    return sorted(set(out))
