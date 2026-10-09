package com.forrestlasiter.umbra.vpn

import android.content.Context
import com.forrestlasiter.umbra.system.WireGuardTunnel
import com.forrestlasiter.umbra.wg.WireGuardBackend

/**
 * The process's one WireGuard tunnel.
 *
 * A tunnel is state that outlives any single screen or broadcast: it is up or it
 * is not. If each caller built its own WireGuardBackend, each would hold its own
 * idea of that state, and a second one would report "down" while the first one's
 * tunnel was running. So everything that touches the tunnel goes through here.
 */
object Tunnels {

    @Volatile private var backend: WireGuardBackend? = null

    private fun backend(context: Context): WireGuardBackend =
        backend ?: synchronized(this) {
            backend ?: WireGuardBackend(context.applicationContext).also { backend = it }
        }

    /** True when this build contains a real tunnel, not the OS-build stand-in. */
    val bundled: Boolean by lazy {
        try {
            Class.forName("com.wireguard.android.backend.GoBackend")
            true
        } catch (e: ClassNotFoundException) {
            false
        }
    }

    /**
     * What to do when the OS starts the always-on VPN by itself (after a reboot).
     * Set by UmbraApp; called by the WireGuard backend, which is the one that
     * hears about it from the library.
     */
    @Volatile var onAlwaysOn: (() -> Unit)? = null

    /** Create the backend now, so it is listening before the OS calls. */
    fun prepare(context: Context) { backend(context) }

    fun wireGuard(context: Context): WireGuardTunnel = object : WireGuardTunnel {
        override val bundled: Boolean get() = Tunnels.bundled
        override val isUp: Boolean get() = backend(context).isUp
        override fun up(config: String) = backend(context).up(config)
        override fun down() = backend(context).down()
    }
}
