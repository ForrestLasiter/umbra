package com.forrestlasiter.umbra.vpn

import android.content.Context
import com.forrestlasiter.umbra.core.PosturePlan
import com.forrestlasiter.umbra.tor.OrbotHelper
import com.forrestlasiter.umbra.wg.WgConfigStore
import com.forrestlasiter.umbra.wg.WireGuardBackend

/**
 * Picks the right enforcement datapath for a posture (see TunnelMode) and drives
 * it:
 *   - TOR          -> orchestrate Orbot (Tor's VPN mode carries all traffic);
 *   - WIREGUARD    -> the WireGuard tunnel (full capture);
 *   - DNS_SINKHOLE -> the local DNS filter (UmbraVpnService);
 *   - NONE         -> nothing this device can enforce.
 *
 * One app-level VPN consent (VpnService.prepare) covers the WireGuard/sinkhole
 * datapaths; Orbot asks for its own consent.
 */
class TunnelController(private val context: Context) {

    private val wg by lazy { WireGuardBackend(context) }
    private val store by lazy { WgConfigStore(context) }

    fun modeFor(plan: PosturePlan): TunnelMode = TunnelMode.forPlan(plan)

    /** Start enforcement. Returns null on success, else a user-facing error. */
    fun activate(profile: String, plan: PosturePlan): String? = when (modeFor(plan)) {
        TunnelMode.TOR -> {
            if (!OrbotHelper.isInstalled(context))
                "Install Orbot to route '${profile}' through Tor."
            else { OrbotHelper.requestStart(context); null }
        }
        TunnelMode.WIREGUARD -> {
            val cfg = store.load()
            if (cfg == null) "Import a WireGuard config first (this profile tunnels all traffic)."
            else runCatching { wg.up(cfg) }
                .fold({ null }, { "WireGuard failed to start: ${it.message}" })
        }
        TunnelMode.DNS_SINKHOLE -> { UmbraVpnService.start(context, profile); null }
        TunnelMode.NONE -> "Nothing on this device to enforce for '$profile'."
    }

    fun deactivate(plan: PosturePlan) {
        when (modeFor(plan)) {
            TunnelMode.WIREGUARD -> runCatching { wg.down() }
            TunnelMode.TOR -> Unit                 // Orbot is toggled in Orbot
            else -> UmbraVpnService.stop(context)
        }
    }
}
