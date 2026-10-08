package com.forrestlasiter.umbra.system

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The firewall/discovery controls only REQUEST a change; a root service in the OS
 * makes it. These tests pin down the promise that matters: the control reports
 * success only when the service confirms, and never when it is absent or silent.
 */
class NetHookControlTest {

    /**
     * System properties plus, optionally, a stand-in for the OS service: when
     * [serviceRuns] is true, writing a request updates the status the way
     * umbra-net.sh would.
     */
    private class FakeProps(var serviceRuns: Boolean, booted: Boolean = serviceRuns) : PropertyStore {
        val values = mutableMapOf<String, String>()
        var refuseWrites = false

        init { if (booted) publish() }

        override fun get(key: String): String = values[key] ?: ""

        override fun set(key: String, value: String): Boolean {
            if (refuseWrites) return false
            values[key] = value
            if (serviceRuns) publish()
            return true
        }

        private fun publish() {
            val inbound = if (values[INBOUND] == "1") 1 else 0
            val discovery = if (values[DISCOVERY] == "1") 1 else 0
            values[NetHookControl.STATUS_KEY] = "inbound=$inbound discovery=$discovery"
        }
    }

    private fun firewall(props: PropertyStore) =
        NetHookControl("firewall", INBOUND, "inbound", props, settle = {})

    @Test fun status_line_is_parsed_into_fields() {
        assertEquals(mapOf("inbound" to "1", "discovery" to "0"),
            NetHookControl.parseStatus("inbound=1 discovery=0"))
        assertTrue(NetHookControl.parseStatus("").isEmpty())
        assertTrue(NetHookControl.parseStatus("error").isEmpty())
    }

    @Test fun enforce_succeeds_once_the_service_confirms() {
        val props = FakeProps(serviceRuns = true)
        val control = firewall(props)
        assertTrue(control.available())
        assertEquals("0", control.snapshot())
        assertTrue(control.enforce())
        assertEquals(true, control.isEnforced())
        assertEquals("inbound=1 discovery=0", props.get(NetHookControl.STATUS_KEY))
    }

    @Test fun restore_puts_back_what_was_recorded() {
        val control = firewall(FakeProps(serviceRuns = true))
        val prior = control.snapshot()!!
        control.enforce()
        assertTrue(control.restore(prior))
        assertEquals(false, control.isEnforced())
    }

    @Test fun an_os_without_the_service_is_unavailable_and_untouched() {
        val props = FakeProps(serviceRuns = false)
        val control = firewall(props)
        assertFalse(control.available())
        assertNull(control.snapshot())         // unreadable, so PostureApplier changes nothing
        assertNull(control.isEnforced())
    }

    @Test fun a_request_the_service_never_confirms_is_a_failure() {
        // The service reported once at boot, then stopped responding.
        val props = FakeProps(serviceRuns = false, booted = true)
        val control = firewall(props)
        assertTrue(control.available())
        assertFalse(control.enforce())         // asked, but never confirmed
        assertEquals(false, control.isEnforced())
    }

    @Test fun a_refused_property_write_is_a_failure() {
        val props = FakeProps(serviceRuns = true).apply { refuseWrites = true }
        assertFalse(firewall(props).enforce())
    }

    @Test fun the_two_switches_do_not_disturb_each_other() {
        val props = FakeProps(serviceRuns = true)
        val fw = firewall(props)
        val discovery = NetHookControl("discovery", DISCOVERY, "discovery", props, settle = {})
        assertTrue(fw.enforce())
        assertEquals(false, discovery.isEnforced())
        assertTrue(discovery.enforce())
        assertEquals(true, fw.isEnforced())
    }

    private companion object {
        const val INBOUND = "persist.umbra.net.inbound_drop"
        const val DISCOVERY = "persist.umbra.net.discovery_drop"
    }
}
