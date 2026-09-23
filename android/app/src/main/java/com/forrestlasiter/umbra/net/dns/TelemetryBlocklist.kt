package com.forrestlasiter.umbra.net.dns

import com.forrestlasiter.umbra.core.CoreSpec

/**
 * Domain matcher for the DNS sinkhole. Domains come from the shared core spec
 * (the same lists the Linux /etc/hosts sinkhole uses), so the phone and the
 * laptop block exactly the same telemetry.
 */
class TelemetryBlocklist(domains: Set<String>) {

    private val blocked: Set<String> = domains.map { it.lowercase().trimEnd('.') }.toSet()

    val size: Int get() = blocked.size

    /** True if [qName] is a blocked domain or a subdomain of one. */
    fun isBlocked(qName: String): Boolean {
        val name = qName.lowercase().trimEnd('.')
        if (name in blocked) return true
        // walk parent domains: a.b.example.com -> b.example.com -> example.com
        var idx = name.indexOf('.')
        while (idx != -1) {
            if (name.substring(idx + 1) in blocked) return true
            idx = name.indexOf('.', idx + 1)
        }
        return false
    }

    companion object {
        fun forProfile(spec: CoreSpec, profile: String): TelemetryBlocklist =
            TelemetryBlocklist(spec.telemetryDomains(profile))
    }
}
