package com.forrestlasiter.umbra.system

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The WireGuard control ties two things together: the tunnel and Android's
 * always-on lockdown (the killswitch). These tests fake both and pin down the
 * ORDER they are touched in, because the order is what keeps the phone from
 * either leaking or being stranded offline.
 */
class WireGuardControlTest {

    private val us = UMBRA_APP

    private class FakeTunnel(
        override val bundled: Boolean = true,
        val events: MutableList<String>,
        var failToStart: Boolean = false,
    ) : WireGuardTunnel {
        override var isUp = false
        override fun up(config: String) {
            if (failToStart) throw IllegalStateException("no route to endpoint")
            events += "tunnel up"
            isUp = true
        }
        override fun down() { events += "tunnel down"; isUp = false }
    }

    private val events = mutableListOf<String>()
    private fun control(alwaysOn: FakeAlwaysOn, tunnel: FakeTunnel, config: String? = "[Interface]") =
        WireGuardControl(us, vpnSlot(alwaysOn), tunnel, { config })

    @Test fun enforce_brings_the_tunnel_up_before_turning_lockdown_on() {
        val alwaysOn = FakeAlwaysOn(events = events)
        val tunnel = FakeTunnel(events = events)
        val wireguard = control(alwaysOn, tunnel)
        assertEquals("|false", wireguard.snapshot())
        assertTrue(wireguard.enforce())
        assertEquals(us, alwaysOn.authorized)                   // no consent dialog needed
        assertEquals(listOf("tunnel up", "always-on=$us lockdown=true"), events)
        assertEquals(true, wireguard.isEnforced())
    }

    @Test fun restore_lifts_lockdown_before_taking_the_tunnel_down() {
        val alwaysOn = FakeAlwaysOn(events = events)
        val tunnel = FakeTunnel(events = events)
        val wireguard = control(alwaysOn, tunnel)
        val prior = wireguard.snapshot()!!
        wireguard.enforce()
        events.clear()
        assertTrue(wireguard.restore(prior))
        // The other order would leave a killswitch up with no tunnel behind it.
        assertEquals(listOf("always-on=null lockdown=false", "tunnel down"), events)
        assertEquals(false, wireguard.isEnforced())
    }

    @Test fun another_vpn_app_that_was_always_on_gets_its_place_back() {
        val alwaysOn = FakeAlwaysOn(app = "com.example.vpn", lockdown = true, events = events)
        val wireguard = control(alwaysOn, FakeTunnel(events = events))
        val prior = wireguard.snapshot()!!
        assertEquals("com.example.vpn|true", prior)
        wireguard.enforce()
        wireguard.restore(prior)
        assertEquals("com.example.vpn", alwaysOn.app)
        assertTrue(alwaysOn.lockdown)
    }

    @Test fun when_another_app_holds_the_slot_it_is_taken_before_the_tunnel_starts() {
        // Android refuses to start a second VPN while another app is always-on,
        // so here the order is the reverse of the usual one.
        val alwaysOn = FakeAlwaysOn(app = TOR_APP, lockdown = true, events = events)
        val wireguard = control(alwaysOn, FakeTunnel(events = events))
        assertTrue(wireguard.enforce())
        assertEquals(listOf("always-on=$us lockdown=true", "tunnel up"), events)
    }

    @Test fun a_tunnel_that_will_not_start_never_gets_lockdown() {
        val alwaysOn = FakeAlwaysOn(events = events)
        val wireguard = control(alwaysOn, FakeTunnel(events = events, failToStart = true))
        assertFalse(wireguard.enforce())
        assertFalse(alwaysOn.lockdown)                          // not stranded offline
        assertTrue(wireguard.diagnostic().contains("no route to endpoint"))
    }

    @Test fun lockdown_the_os_refuses_is_a_failure_not_a_half_success() {
        val alwaysOn = FakeAlwaysOn(events = events, refuseSet = true)
        val wireguard = control(alwaysOn, FakeTunnel(events = events))
        assertFalse(wireguard.enforce())                        // tunnel alone is not "enforced"
        assertEquals(false, wireguard.isEnforced())
    }

    @Test fun each_reason_it_can_be_unavailable_is_named() {
        val tunnel = FakeTunnel(events = events)
        assertTrue(control(FakeAlwaysOn(events = events), FakeTunnel(bundled = false, events = events))
            .unavailableReason()!!.contains("does not include a WireGuard tunnel"))
        assertTrue(control(FakeAlwaysOn(events = events, readable = false), tunnel)
            .unavailableReason()!!.contains("always-on VPN"))
        assertTrue(control(FakeAlwaysOn(events = events), tunnel, config = null)
            .unavailableReason()!!.contains("import"))
        assertNull(control(FakeAlwaysOn(events = events), tunnel).unavailableReason())
    }

    @Test fun unavailable_means_nothing_is_snapshotted_or_changed() {
        val alwaysOn = FakeAlwaysOn(events = events)
        val wireguard = control(alwaysOn, FakeTunnel(events = events), config = null)
        assertFalse(wireguard.available())
        assertNull(wireguard.snapshot())
        assertTrue(events.isEmpty())
    }
}
