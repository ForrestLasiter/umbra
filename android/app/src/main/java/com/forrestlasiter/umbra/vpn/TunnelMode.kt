package com.forrestlasiter.umbra.vpn

import com.forrestlasiter.umbra.core.PlannedAction
import com.forrestlasiter.umbra.core.PosturePlan

/**
 * Which enforcement datapath a posture uses on this device. Pure selection logic
 * (no Android types) so it is unit-testable. Precedence reflects "go dark":
 *   tor  >  wireguard  >  telemetry-only  >  nothing.
 * paranoid (which needs both tor and wireguard) therefore routes through Tor.
 */
enum class TunnelMode {
    TOR, WIREGUARD, DNS_SINKHOLE, NONE;

    companion object {
        // ENFORCE is deliberately absent: it means the capability is already
        // enforced WITHOUT a tunnel. On an OS build `telemetry` is ENFORCE (the
        // resolver's hosts sinkhole does it), so it must not also grab the VPN
        // slot for a DNS filter -- freeing that slot is the point.
        private val ENFORCED_BY_TUNNEL = setOf(
            PlannedAction.REQUEST_CONSENT, PlannedAction.NEEDS_TUNNEL,
        )

        private fun PosturePlan.tunnels(capability: String): Boolean =
            items.any { it.capability == capability && it.action in ENFORCED_BY_TUNNEL }

        fun forPlan(plan: PosturePlan): TunnelMode = when {
            plan.tunnels("tor") -> TOR
            plan.tunnels("wireguard") -> WIREGUARD
            plan.tunnels("telemetry") -> DNS_SINKHOLE
            else -> NONE
        }
    }
}
