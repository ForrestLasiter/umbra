package com.forrestlasiter.umbra.wg

import android.content.Context

/**
 * PLATFORM BUILD ONLY (compiled by Android.bp, never by Gradle).
 *
 * The normal app tunnels with the official WireGuard userspace library, fetched
 * from Maven by Gradle. An OS source tree does not contain that library, so this
 * file stands in for app/.../wg/WireGuardBackend.kt with the same shape and an
 * honest answer: it refuses, and says why. TunnelController turns the exception
 * into the message the user sees, so a WireGuard posture on an OS build reports
 * "not available" instead of pretending to be up.
 *
 * This goes away when the OS build gets a real tunnel (kernel WireGuard driven as
 * an always-on VPN) -- at that point this file becomes that implementation.
 */
class WireGuardBackend(@Suppress("UNUSED_PARAMETER") context: Context) {

    val isUp: Boolean get() = false

    fun up(@Suppress("UNUSED_PARAMETER") configText: String) {
        throw UnsupportedOperationException(
            "this OS build does not include a WireGuard tunnel yet"
        )
    }

    fun down() = Unit
}
