package com.forrestlasiter.umbra.wg

import android.content.Context
import com.wireguard.android.backend.Backend
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import java.io.BufferedReader
import java.io.StringReader

/**
 * Brings a WireGuard tunnel up/down using the official wireguard-android
 * userspace backend (libwg-go) — the same engine the WireGuard app ships. We do
 * not implement the crypto; we hand the parsed config to GoBackend, which owns
 * the tun, the handshake, and encrypted forwarding to the endpoint.
 *
 * DEVICE-TEST PENDING: this glue is written against the library's public API but
 * cannot be exercised on the build host (no Android runtime / native lib). The
 * pure config layer (WgConfig) IS unit-tested.
 */
class WireGuardBackend(context: Context) {

    private val backend: Backend = GoBackend(context.applicationContext)
    private val tunnel = UmbraTunnel()

    val isUp: Boolean get() = tunnel.state == Tunnel.State.UP

    /** Parse [configText] and bring the tunnel up. Throws on a bad config / failure. */
    fun up(configText: String) {
        val config = Config.parse(BufferedReader(StringReader(configText)))
        backend.setState(tunnel, Tunnel.State.UP, config)
    }

    fun down() {
        backend.setState(tunnel, Tunnel.State.DOWN, null)
    }

    private class UmbraTunnel : Tunnel {
        @Volatile var state: Tunnel.State = Tunnel.State.DOWN
        override fun getName(): String = "umbra"          // [a-zA-Z0-9_=+.-]{1,15}
        override fun onStateChange(newState: Tunnel.State) { state = newState }
    }
}
