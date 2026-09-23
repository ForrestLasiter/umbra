package com.forrestlasiter.umbra.net.dns

import com.forrestlasiter.umbra.core.CoreSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TelemetryBlocklistTest {

    private val list = TelemetryBlocklist(setOf("graph.facebook.com", "app-measurement.com"))

    @Test fun exact_match_is_blocked() {
        assertTrue(list.isBlocked("graph.facebook.com"))
    }

    @Test fun subdomain_is_blocked() {
        assertTrue(list.isBlocked("edge.graph.facebook.com"))
    }

    @Test fun trailing_dot_and_case_are_normalized() {
        assertTrue(list.isBlocked("Graph.Facebook.Com."))
    }

    @Test fun unrelated_domain_is_allowed() {
        assertFalse(list.isBlocked("facebook.com"))          // parent of a blocked host, not blocked
        assertFalse(list.isBlocked("example.com"))
        assertFalse(list.isBlocked("notgraph.facebook.com.evil.com"))
    }

    @Test fun builds_from_spec_union_of_a_profiles_lists() {
        val spec = CoreSpec.parse(SPEC)
        val home = TelemetryBlocklist.forProfile(spec, "home")
        assertTrue(home.isBlocked("www.google-analytics.com"))
        assertTrue(home.isBlocked("metrics.mozilla.org"))
        assertEquals(3, home.size)                          // union of both lists
        assertEquals(0, TelemetryBlocklist.forProfile(spec, "normal").size)
    }

    private companion object {
        const val SPEC = """
        {
          "umbra_spec_version": "1", "engine_version": "0.1.0",
          "enforcement_levels": [], "capabilities": {}, "platforms": {},
          "telemetry_blocklists": {
            "os": ["metrics.mozilla.org"],
            "common-trackers": ["www.google-analytics.com", "app-measurement.com"]
          },
          "profiles": {
            "home": {"description": "", "fail_mode": "open", "requires": [],
                     "telemetry_blocklists": ["os", "common-trackers"]},
            "normal": {"description": "", "fail_mode": "open", "requires": [],
                       "telemetry_blocklists": []}
          }
        }
        """
    }
}
