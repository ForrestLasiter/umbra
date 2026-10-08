package com.forrestlasiter.umbra.system

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The telemetry control flips a property and then PROVES the result by resolving
 * a blocked domain. These tests fake the properties and the resolver to pin down
 * that it only ever reports "enforced" when the lookup really comes back empty-
 * handed (the unspecified address).
 */
class TelemetryControlTest {

    private class Props(vararg initial: Pair<String, String>) : PropertyStore {
        val values = mutableMapOf(*initial)
        override fun get(key: String) = values[key] ?: ""
        override fun set(key: String, value: String): Boolean { values[key] = value; return true }
    }

    private val supported = TelemetryControl.SUPPORT_KEY to "1"
    private val canary = "metrics.example.org"

    /** A resolver that behaves like a patched OS: sinkholed only while the switch is on. */
    private fun patchedResolver(props: Props): (String) -> List<String>? = { host ->
        if (props.get(TelemetryControl.REQUEST_KEY) == "1" && host == canary) listOf("0.0.0.0", "::")
        else listOf("203.0.113.7")
    }

    private fun control(props: Props, resolve: (String) -> List<String>?) =
        TelemetryControl(canary, props, resolve, settle = {})

    @Test fun enforce_succeeds_when_the_canary_resolves_to_nowhere() {
        val props = Props(supported)
        val telemetry = control(props, patchedResolver(props))
        assertTrue(telemetry.available())
        assertEquals("0", telemetry.snapshot())
        assertTrue(telemetry.enforce())
        assertEquals(true, telemetry.isEnforced())
    }

    @Test fun an_os_that_claims_support_but_is_not_patched_is_caught() {
        // The property is set, but lookups still return the real address.
        val props = Props(supported)
        val telemetry = control(props) { listOf("203.0.113.7") }
        assertFalse(telemetry.enforce())
        assertEquals(false, telemetry.isEnforced())
    }

    @Test fun a_partly_blocked_answer_does_not_count() {
        val props = Props(supported)
        val telemetry = control(props) { listOf("0.0.0.0", "203.0.113.7") }
        assertFalse(telemetry.enforce())
    }

    @Test fun a_failed_lookup_is_not_mistaken_for_blocking() {
        // Offline looks like "no answer", which must never read as "enforced".
        val props = Props(supported)
        val telemetry = control(props) { null }
        assertFalse(telemetry.enforce())
    }

    @Test fun without_os_support_it_is_unavailable_and_untouched() {
        val props = Props()
        val telemetry = control(props, patchedResolver(props))
        assertFalse(telemetry.available())
        assertNull(telemetry.snapshot())
    }

    @Test fun without_a_domain_to_test_with_it_is_unavailable() {
        val props = Props(supported)
        assertFalse(TelemetryControl(null, props, { listOf("0.0.0.0") }, settle = {}).available())
    }

    @Test fun restore_puts_the_switch_back() {
        val props = Props(supported)
        val telemetry = control(props, patchedResolver(props))
        val prior = telemetry.snapshot()!!
        telemetry.enforce()
        assertTrue(telemetry.restore(prior))
        assertEquals("0", props.get(TelemetryControl.REQUEST_KEY))
        assertEquals(false, telemetry.isEnforced())
    }
}
