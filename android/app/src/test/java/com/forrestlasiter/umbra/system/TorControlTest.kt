package com.forrestlasiter.umbra.system

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Tor control does not run Tor; it pins the Tor app as Android's always-on
 * VPN with lockdown. These tests fake the setting and the app, and pin down what
 * "enforced" is allowed to mean -- and what happens to the one always-on slot
 * when the WireGuard control wants it too.
 */
class TorControlTest {

    private class FakeTor(override var installed: Boolean = true) : TorProvider {
        override val packageName = TOR_APP
    }

    private class FakeTunnel : WireGuardTunnel {
        override val bundled = true
        override var isUp = false
        override fun up(config: String) { isUp = true }
        override fun down() { isUp = false }
    }

    private val alwaysOn = FakeAlwaysOn()
    private val store = MemoryStore()
    private val slot = vpnSlot(alwaysOn, store)
    private val orbot = FakeTor()

    /** A Tor control whose wait ends at once, with Tor connected or not. */
    private fun tor(connects: Boolean = true) =
        TorControl(slot, orbot, await = { condition -> if (connects) alwaysOn.active = TOR_APP; condition() })

    private fun wireguard() = WireGuardControl(UMBRA_APP, slot, FakeTunnel(), { "[Interface]" })

    @Test fun enforce_pins_the_tor_app_with_lockdown_and_no_dialog() {
        val control = tor()
        assertTrue(control.enforce())
        assertEquals(TOR_APP, alwaysOn.authorized)
        assertEquals(TOR_APP, alwaysOn.app)
        assertTrue(alwaysOn.lockdown)
        assertEquals(true, control.isEnforced())
    }

    @Test fun tor_that_never_connects_is_a_failure_but_stays_fail_closed() {
        val control = tor(connects = false)
        assertFalse(control.enforce())                  // not "enforced": no VPN yet
        assertTrue(alwaysOn.lockdown)                   // ...but nothing leaks meanwhile
        assertTrue(control.diagnostic().contains("blocked until it does"))
    }

    @Test fun lockdown_alone_is_not_reported_as_enforced() {
        val control = tor()
        control.enforce()
        alwaysOn.active = null                          // Orbot stopped or crashed
        assertEquals(false, control.isEnforced())
    }

    @Test fun another_apps_vpn_being_up_does_not_count() {
        val control = tor(connects = false)
        alwaysOn.active = UMBRA_APP                     // e.g. the WireGuard tunnel, mid hand-over
        assertFalse(control.enforce())
    }

    @Test fun re_asserting_a_posture_that_holds_does_not_restart_tor() {
        val control = tor()
        control.enforce()
        alwaysOn.events.clear()
        assertTrue(control.enforce())
        assertTrue(alwaysOn.events.isEmpty())
    }

    @Test fun re_asserting_while_tor_is_still_starting_waits_instead_of_restarting_it() {
        tor(connects = false).enforce()                 // pinned, not connected yet
        alwaysOn.events.clear()
        assertTrue(tor(connects = true).enforce())      // it connects during the wait
        assertTrue(alwaysOn.events.isEmpty())
    }

    @Test fun re_asserting_when_tor_stays_down_pins_it_again_so_android_restarts_it() {
        tor().enforce()
        alwaysOn.active = null
        alwaysOn.events.clear()
        assertFalse(tor(connects = false).enforce())    // still down: not "enforced"
        assertEquals(listOf("always-on=$TOR_APP lockdown=true"), alwaysOn.events)
    }

    @Test fun restore_puts_back_what_was_there_before() {
        alwaysOn.app = "com.example.vpn"
        val control = tor()
        control.enforce()
        assertTrue(control.restore("ignored"))
        assertEquals("com.example.vpn", alwaysOn.app)
        assertFalse(alwaysOn.lockdown)
        assertNull(store.get(VpnSlot.KEY))
    }

    @Test fun without_the_tor_app_it_is_unavailable_and_changes_nothing() {
        orbot.installed = false
        val control = tor()
        assertFalse(control.available())
        assertTrue(control.unavailableReason()!!.contains("Orbot"))
        assertNull(control.snapshot())
        assertNull(alwaysOn.app)
    }

    // --- the shared slot: switching between the two tunnel profiles ---------

    @Test fun wireguard_to_tor_hands_lockdown_over_without_a_gap() {
        val wg = wireguard()
        val tor = tor()
        wg.enforce()
        alwaysOn.events.clear()
        // The applier enforces the new control first, then restores the old one.
        assertTrue(tor.enforce())
        assertTrue(wg.restore("ignored"))
        // One change only: lockdown moved straight to the Tor app, never off.
        assertEquals(listOf("always-on=$TOR_APP lockdown=true"), alwaysOn.events)
    }

    @Test fun tor_to_wireguard_hands_lockdown_over_without_a_gap() {
        val wg = wireguard()
        val tor = tor()
        tor.enforce()
        alwaysOn.events.clear()
        assertTrue(wg.enforce())
        assertTrue(tor.restore("ignored"))
        assertEquals(listOf("always-on=$UMBRA_APP lockdown=true"), alwaysOn.events)
    }

    @Test fun after_any_number_of_switches_normal_returns_the_original_setting() {
        alwaysOn.app = "com.example.vpn"
        alwaysOn.lockdown = true
        val wg = wireguard()
        val tor = tor()
        wg.enforce()
        tor.enforce(); wg.restore("ignored")
        wg.enforce(); tor.restore("ignored")
        tor.enforce(); wg.restore("ignored")
        assertTrue(tor.restore("ignored"))              // -> normal
        assertEquals("com.example.vpn", alwaysOn.app)   // not one of Umbra's own pins
        assertTrue(alwaysOn.lockdown)
        assertNull(store.get(VpnSlot.KEY))
    }

    @Test fun a_setting_the_user_changed_afterwards_is_left_alone() {
        val control = tor()
        control.enforce()
        alwaysOn.app = "com.example.vpn"                // the user picked another VPN
        alwaysOn.lockdown = false
        alwaysOn.events.clear()
        assertTrue(control.restore("ignored"))
        assertTrue(alwaysOn.events.isEmpty())
        assertEquals("com.example.vpn", alwaysOn.app)
    }
}
