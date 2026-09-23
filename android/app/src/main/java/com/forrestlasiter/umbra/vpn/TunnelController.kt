package com.forrestlasiter.umbra.vpn

import android.content.Context
import com.forrestlasiter.umbra.core.PlannedAction
import com.forrestlasiter.umbra.core.PosturePlan
import com.forrestlasiter.umbra.wg.WgConfigStore
import com.forrestlasiter.umbra.wg.WireGuardBackend

/**
 * Picks the right enforcement datapath for a posture and drives it:
 *   - a posture that needs WireGuard  -> the WireGuard tunnel (full capture);
 *   - a posture that only needs telemetry -> the DNS sinkhole (UmbraVpnService);
 *   - otherwise -> nothing this device can enforce.
 *
 * One app-level VPN consent (VpnService.prepare) covers both datapaths, so the UI
 * asks for it once before calling activate().
 */
class TunnelController(private val context: Context) {

    enum class Mode { WIREGUARD, DNS_SINKHOLE, NONE }

    private val wg by lazy { WireGuardBackend(context) }
    private val store by lazy { WgConfigStore(context) }

    fun modeFor(plan: PosturePlan): Mode {
        val needsWg = plan.items.any {
            it.capability == "wireguard" && it.action == PlannedAction.REQUEST_CONSENT
        }
        if (needsWg) return Mode.WIREGUARD
        val needsTelemetry = plan.items.any {
            it.capability == "telemetry" && it.action != PlannedAction.UNAVAILABLE
        }
        return if (needsTelemetry) Mode.DNS_SINKHOLE else Mode.NONE
    }

    /** Start enforcement. Returns null on success, else a user-facing error. */
    fun activate(profile: String, plan: PosturePlan): String? = when (modeFor(plan)) {
        Mode.WIREGUARD -> {
            val cfg = store.load()
            if (cfg == null) "Import a WireGuard config first (this profile tunnels all traffic)."
            else runCatching { wg.up(cfg) }
                .fold({ null }, { "WireGuard failed to start: ${it.message}" })
        }
        Mode.DNS_SINKHOLE -> { UmbraVpnService.start(context, profile); null }
        Mode.NONE -> "Nothing on this device to enforce for '$profile'."
    }

    fun deactivate(plan: PosturePlan) {
        when (modeFor(plan)) {
            Mode.WIREGUARD -> runCatching { wg.down() }
            else -> UmbraVpnService.stop(context)
        }
    }
}
