package com.forrestlasiter.umbra.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-JVM tests over the same core spec the app ships. They prove the Android
 * adapter reads the contract correctly and stays HONEST — a capability the matrix
 * marks advisory must never surface as enforced.
 */
class PostureEngineTest {

    // A trimmed but shape-accurate spec (the real one is assets/umbra-core.json).
    private val specJson = """
    {
      "umbra_spec_version": "1",
      "engine_version": "0.1.0",
      "enforcement_levels": [],
      "capabilities": {
        "telemetry": {"description": "Block phone-home.", "controls": []},
        "mac": {"description": "Randomize MAC.", "controls": []},
        "kernel": {"description": "Kernel hardening.", "controls": []},
        "wireguard": {"description": "Tunnel.", "controls": []}
      },
      "platforms": {
        "android": {"description": "VPNService", "capabilities": {
          "telemetry": {"level": "requires_vpn_profile", "reason": "DNS filter"},
          "mac": {"level": "advisory", "reason": "OS owns it"},
          "kernel": {"level": "requires_rooted_os", "reason": "needs root"},
          "wireguard": {"level": "requires_entitlement", "reason": "VPN consent"}
        }}
      },
      "profiles": {
        "travel": {"description": "", "fail_mode": "closed",
                   "requires": ["telemetry", "mac", "kernel", "wireguard"]}
      }
    }
    """.trimIndent()

    private fun spec() = CoreSpec.parse(specJson)

    @Test fun plan_covers_every_required_capability() {
        val plan = PostureEngine.plan(spec(), "travel")
        assertEquals(listOf("telemetry", "mac", "kernel", "wireguard"),
            plan.items.map { it.capability })
    }

    @Test fun advisory_capability_is_never_reported_as_enforced() {
        val mac = PostureEngine.plan(spec(), "travel").items.first { it.capability == "mac" }
        assertEquals(PlannedAction.GUIDE_TO_SETTING, mac.action)
        assertTrue(!mac.honestlyOn)
    }

    @Test fun root_only_capability_is_marked_needs_root() {
        val kernel = PostureEngine.plan(spec(), "travel").items.first { it.capability == "kernel" }
        assertEquals(PlannedAction.NEEDS_ROOT, kernel.action)
    }

    @Test fun tunnel_capabilities_drive_the_vpn() {
        val plan = PostureEngine.plan(spec(), "travel")
        val enforceableCaps = plan.enforceable.map { it.capability }.toSet()
        assertTrue(enforceableCaps.contains("telemetry"))   // via tunnel
        assertTrue(enforceableCaps.contains("wireguard"))   // on consent
        assertTrue(!enforceableCaps.contains("mac"))        // advisory, not enforced
    }

    @Test fun enforcement_actionable_flags_are_correct() {
        assertTrue(Enforcement.ENFORCED.actionable)
        assertTrue(Enforcement.REQUIRES_VPN_PROFILE.actionable)
        assertTrue(!Enforcement.ADVISORY.actionable)
        assertTrue(!Enforcement.UNAVAILABLE.actionable)
    }
}
