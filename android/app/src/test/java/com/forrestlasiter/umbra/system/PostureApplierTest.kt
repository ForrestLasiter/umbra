package com.forrestlasiter.umbra.system

import com.forrestlasiter.umbra.core.CoreSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-JVM tests for the system-posture logic. No phone needed: the controls and
 * the snapshot store are fakes, so what is under test is the ORDER and the
 * BOOKKEEPING -- the two things that decide whether leaving a posture really
 * returns the phone to how it was.
 */
class PostureApplierTest {

    /** A control whose "system setting" is just a string we can inspect. */
    private class FakeControl(
        override val capability: String,
        var state: String? = "original",
        var refuseRestore: Boolean = false,
        private val events: MutableList<String> = mutableListOf(),
        var present: Boolean = true,
    ) : SystemControl {
        override fun available(): Boolean = present
        override fun snapshot(): String? = state
        override fun enforce(): Boolean { events += "enforce:$capability"; state = "dark"; return true }
        override fun restore(prior: String): Boolean {
            if (refuseRestore) return false
            state = prior
            return true
        }
        override fun isEnforced(): Boolean = state == "dark"
    }

    private class MapStore(private val events: MutableList<String> = mutableListOf()) : SnapshotStore {
        val map = mutableMapOf<String, String>()
        override fun get(capability: String) = map[capability]
        override fun put(capability: String, prior: String) { events += "snapshot:$capability"; map[capability] = prior }
        override fun remove(capability: String) { map.remove(capability) }
        override var activeProfile: String? = null
    }

    // Two capabilities the system build enforces, one it does not (kernel).
    private val spec = CoreSpec.parse(
        """
        {
          "umbra_spec_version": "1", "engine_version": "0.1.0",
          "platforms": {
            "android": {"description": "", "capabilities": {
              "mac": {"level": "advisory", "reason": ""},
              "bluetooth_off": {"level": "advisory", "reason": ""},
              "kernel": {"level": "requires_rooted_os", "reason": ""}
            }},
            "android_system": {"description": "", "capabilities": {
              "mac": {"level": "enforced", "reason": ""},
              "bluetooth_off": {"level": "enforced", "reason": ""},
              "kernel": {"level": "requires_rooted_os", "reason": ""}
            }}
          },
          "profiles": {
            "normal": {"requires": []},
            "home": {"requires": ["mac", "kernel"]},
            "travel": {"requires": ["mac", "kernel", "bluetooth_off"]}
          }
        }
        """.trimIndent()
    )
    private val system = CoreSpec.PLATFORM_ANDROID_SYSTEM

    @Test fun snapshot_is_stored_before_the_control_mutates() {
        val events = mutableListOf<String>()
        val applier = PostureApplier(listOf(FakeControl("mac", events = events)), MapStore(events))
        applier.reconcile(setOf("mac"))
        assertEquals(listOf("snapshot:mac", "enforce:mac"), events)
    }

    @Test fun only_capabilities_the_platform_enforces_are_wanted() {
        // kernel is required by the profile but not ENFORCED here: not our job.
        assertEquals(setOf("mac"), PostureApplier.wantedFor(spec, "home", system))
        // The ordinary app enforces none of these with system controls.
        assertEquals(emptySet<String>(), PostureApplier.wantedFor(spec, "travel", CoreSpec.PLATFORM_ANDROID))
    }

    @Test fun applying_a_profile_enforces_and_records_it() {
        val mac = FakeControl("mac")
        val bt = FakeControl("bluetooth_off")
        val store = MapStore()
        val outcomes = PostureApplier(listOf(mac, bt), store).apply(spec, "home", system)
        assertTrue(mac.isEnforced())
        assertFalse(bt.isEnforced())                       // home does not ask for it
        assertEquals("home", store.activeProfile)
        assertEquals(Change.ENFORCED, outcomes.first { it.capability == "mac" }.change)
        assertEquals(Change.UNTOUCHED, outcomes.first { it.capability == "bluetooth_off" }.change)
    }

    @Test fun switching_profiles_keeps_the_original_snapshot() {
        val mac = FakeControl("mac", state = "original")
        val store = MapStore()
        val applier = PostureApplier(listOf(mac, FakeControl("bluetooth_off")), store)
        applier.apply(spec, "home", system)
        applier.apply(spec, "travel", system)              // mac is kept, not re-snapshotted
        assertEquals("original", store.map["mac"])         // not "dark"
        applier.apply(spec, "normal", system)
        assertEquals("original", mac.state)
    }

    @Test fun dropping_to_a_lighter_profile_restores_what_it_no_longer_needs() {
        val bt = FakeControl("bluetooth_off", state = "on")
        val applier = PostureApplier(listOf(FakeControl("mac"), bt), MapStore())
        applier.apply(spec, "travel", system)
        assertTrue(bt.isEnforced())
        applier.apply(spec, "home", system)                // home has no bluetooth_off
        assertEquals("on", bt.state)
    }

    @Test fun normal_restores_everything_and_forgets_the_posture() {
        val mac = FakeControl("mac", state = "a")
        val bt = FakeControl("bluetooth_off", state = "b")
        val store = MapStore()
        val applier = PostureApplier(listOf(mac, bt), store)
        applier.apply(spec, "travel", system)
        applier.apply(spec, "normal", system)
        assertEquals("a", mac.state)
        assertEquals("b", bt.state)
        assertTrue(store.map.isEmpty())
        assertNull(store.activeProfile)
    }

    @Test fun a_failed_restore_keeps_the_snapshot_and_the_posture_marker() {
        val mac = FakeControl("mac", state = "a", refuseRestore = true)
        val store = MapStore()
        val applier = PostureApplier(listOf(mac), store)
        applier.apply(spec, "home", system)
        val outcomes = applier.apply(spec, "normal", system)
        assertFalse(outcomes.single().ok)
        assertEquals("a", store.map["mac"])                // still owed to the user
        assertEquals("home", store.activeProfile)          // not falsely "normal"
        mac.refuseRestore = false                          // the retry then succeeds
        applier.apply(spec, "normal", system)
        assertEquals("a", mac.state)
        assertNull(store.activeProfile)
    }

    @Test fun a_control_the_os_cannot_support_is_reported_not_enforced() {
        val mac = FakeControl("mac", present = false)
        val store = MapStore()
        val outcome = PostureApplier(listOf(mac), store).apply(spec, "home", system).single()
        assertEquals(Change.UNAVAILABLE, outcome.change)
        assertFalse(mac.isEnforced())
        assertTrue(store.map.isEmpty())                    // nothing to restore later
    }

    @Test fun a_control_that_becomes_unavailable_is_still_restored() {
        val mac = FakeControl("mac", state = "a")
        val applier = PostureApplier(listOf(mac), MapStore())
        applier.apply(spec, "home", system)
        mac.present = false                                // e.g. the OS helper stopped
        applier.apply(spec, "normal", system)
        assertEquals("a", mac.state)                       // we changed it; we put it back
    }

    @Test fun a_control_that_cannot_be_read_is_not_changed() {
        val mac = FakeControl("mac", state = null)
        val store = MapStore()
        val outcome = PostureApplier(listOf(mac), store).reconcile(setOf("mac")).single()
        assertFalse(outcome.ok)
        assertNull(mac.state)                              // enforce() never ran
        assertTrue(store.map.isEmpty())
    }
}
