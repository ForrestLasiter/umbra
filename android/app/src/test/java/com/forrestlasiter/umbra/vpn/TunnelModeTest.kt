package com.forrestlasiter.umbra.vpn

import com.forrestlasiter.umbra.core.CoreSpec
import com.forrestlasiter.umbra.core.PostureEngine
import org.junit.Assert.assertEquals
import org.junit.Test

class TunnelModeTest {

    private fun mode(profile: String) =
        TunnelMode.forPlan(PostureEngine.plan(CoreSpec.parse(SPEC), profile))

    @Test fun paranoid_routes_through_tor_even_though_it_also_needs_wireguard() {
        assertEquals(TunnelMode.TOR, mode("paranoid"))
    }

    @Test fun travel_uses_wireguard() {
        assertEquals(TunnelMode.WIREGUARD, mode("travel"))
    }

    @Test fun home_uses_the_dns_sinkhole() {
        assertEquals(TunnelMode.DNS_SINKHOLE, mode("home"))
    }

    @Test fun a_root_and_advisory_only_posture_enforces_nothing() {
        assertEquals(TunnelMode.NONE, mode("bare"))
    }

    private companion object {
        const val SPEC = """
        {
          "umbra_spec_version": "1", "engine_version": "0.1.0",
          "enforcement_levels": [], "capabilities": {},
          "platforms": { "android": { "description": "", "capabilities": {
            "tor": {"level": "requires_vpn_profile", "reason": ""},
            "wireguard": {"level": "requires_entitlement", "reason": ""},
            "telemetry": {"level": "requires_vpn_profile", "reason": ""},
            "kernel": {"level": "requires_rooted_os", "reason": ""},
            "mac": {"level": "advisory", "reason": ""}
          }}},
          "telemetry_blocklists": {},
          "profiles": {
            "paranoid": {"description": "", "fail_mode": "closed", "requires": ["tor","wireguard","telemetry"]},
            "travel":   {"description": "", "fail_mode": "closed", "requires": ["wireguard","telemetry"]},
            "home":     {"description": "", "fail_mode": "open",   "requires": ["telemetry","mac"]},
            "bare":     {"description": "", "fail_mode": "open",   "requires": ["kernel","mac"]}
          }
        }
        """
    }
}
