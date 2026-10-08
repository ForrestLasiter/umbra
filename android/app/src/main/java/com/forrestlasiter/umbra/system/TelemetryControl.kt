package com.forrestlasiter.umbra.system

import java.net.InetAddress

/**
 * telemetry -- "Block OS/app phone-home and telemetry destinations."
 *
 * The ordinary app does this with a DNS filter inside the VPN slot, which means
 * you cannot also run a real VPN. An OS build can do better: Android's resolver
 * looks a name up in the hosts file BEFORE it sends any DNS query, so a hosts
 * file that maps telemetry domains to the unspecified address (0.0.0.0 / ::)
 * stops them resolving -- over plain DNS, DNS-over-TLS or DNS-over-HTTPS alike,
 * with no process to keep alive and the VPN slot left free. It is the same idea
 * as the Linux build's /etc/hosts sinkhole.
 *
 * The OS side is a small resolver patch plus a generated hosts file (see
 * android/os-integration/). This control only flips the switch:
 *
 *   ro.umbra.dns_sinkhole=1                 the OS says its resolver supports it
 *   persist.umbra.net.telemetry_sinkhole    "1" = read the sinkhole hosts file
 *
 * And then it CHECKS. enforce() resolves a domain from the blocklist (the
 * "canary") and reports success only if the answer really is the unspecified
 * address. An OS that sets the property without carrying the patch therefore
 * fails here, visibly, instead of being reported as blocking.
 *
 * Same honest limit as on Linux: an app that carries its own DNS-over-HTTPS
 * client, or hardcodes IP addresses, never asks the system resolver and is not
 * affected.
 */
class TelemetryControl(
    private val canary: String?,
    private val props: PropertyStore = OsProperties,
    private val resolve: (String) -> List<String>? = ::resolveOffMainThread,
    private val settle: () -> Unit = { Thread.sleep(NetHookControl.POLL_MS) },
) : SystemControl {

    override val capability = "telemetry"

    /** Needs the OS's say-so and a domain to verify with. */
    override fun available(): Boolean = props.get(SUPPORT_KEY) == ON && canary != null

    override fun snapshot(): String? =
        if (available()) (if (props.get(REQUEST_KEY) == ON) ON else OFF) else null

    override fun enforce(): Boolean {
        if (!props.set(REQUEST_KEY, ON)) return false
        // The resolver picks the change up on its next lookup; allow a moment
        // for this process's own short-lived address cache to expire.
        repeat(ATTEMPTS) {
            if (isEnforced() == true) return true
            settle()
        }
        return isEnforced() == true
    }

    /**
     * Turning it off is not verified by lookup: "the canary does not resolve to
     * 0.0.0.0" is also what being offline looks like, so it would prove nothing.
     */
    override fun restore(prior: String): Boolean =
        props.set(REQUEST_KEY, if (prior == ON) ON else OFF)

    /** True only when the canary resolves, and only to unspecified addresses. */
    override fun isEnforced(): Boolean? {
        val domain = canary ?: return null
        val addresses = resolve(domain)
        lastAnswer = addresses
        return addresses != null && addresses.isNotEmpty() && addresses.all { it in UNSPECIFIED }
    }

    private var lastAnswer: List<String>? = null

    override fun diagnostic(): String =
        "$canary resolved to ${lastAnswer ?: "nothing (lookup failed)"}; expected only $UNSPECIFIED"

    companion object {
        const val SUPPORT_KEY = "ro.umbra.dns_sinkhole"
        const val REQUEST_KEY = "persist.umbra.net.telemetry_sinkhole"
        const val ON = "1"
        const val OFF = "0"
        const val ATTEMPTS = 30
        val UNSPECIFIED = setOf("0.0.0.0", "::")

        /**
         * Resolve [host] with the system resolver. Android forbids network calls
         * on the main thread, and a posture is often applied from it (the tile,
         * the command receiver), so the lookup runs on a short-lived thread and
         * this one waits. Returns null if the lookup fails or times out.
         */
        fun resolveOffMainThread(host: String): List<String>? {
            var result: List<String>? = null
            val worker = Thread {
                result = try {
                    InetAddress.getAllByName(host).map { it.hostAddress ?: "" }
                } catch (e: Exception) {
                    null
                }
            }
            worker.start()
            worker.join(LOOKUP_TIMEOUT_MS)
            return result
        }

        private const val LOOKUP_TIMEOUT_MS = 3000L
    }
}
