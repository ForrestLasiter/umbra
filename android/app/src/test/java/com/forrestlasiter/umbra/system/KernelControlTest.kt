package com.forrestlasiter.umbra.system

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The kernel control cannot read most of what it asks init to set, so it leans on
 * one readable sysctl as proof. These tests fake init and check the two things
 * that matter: success is only reported on that proof, and the prior value is
 * recorded once and put back.
 */
class KernelControlTest {

    /**
     * Properties plus a stand-in for init: when [initReacts] is true, a change to
     * the request property moves perf_event_paranoid the way umbra-kernel.rc would.
     */
    private class Device(var paranoid: Int?, var initReacts: Boolean = true, hook: Boolean = true) : PropertyStore {
        val values = mutableMapOf<String, String>()

        init { if (hook) values[KernelControl.HOOK_KEY] = "1" }

        override fun get(key: String) = values[key] ?: ""

        override fun set(key: String, value: String): Boolean {
            values[key] = value
            if (initReacts && key == KernelControl.REQUEST_KEY) {
                paranoid = if (value == "1") 3 else (values[KernelControl.PRIOR_PERF_KEY]?.toIntOrNull() ?: 3)
            }
            return true
        }
    }

    private fun control(device: Device) = KernelControl(device, { device.paranoid }, settle = {})

    @Test fun enforce_succeeds_once_the_readable_sysctl_reads_back_hardened() {
        val device = Device(paranoid = -1)
        val kernel = control(device)
        assertTrue(kernel.available())
        assertEquals("0,-1", kernel.snapshot())
        assertTrue(kernel.enforce())
        assertEquals(3, device.paranoid)
        assertEquals(true, kernel.isEnforced())
    }

    @Test fun restore_puts_the_exact_prior_value_back() {
        // -1 (modern Android) and 1 (older kernels) must both come back as they were.
        for (stock in listOf(-1, 1, 2)) {
            val device = Device(paranoid = stock)
            val kernel = control(device)
            val prior = kernel.snapshot()!!
            kernel.enforce()
            assertTrue(kernel.restore(prior))
            assertEquals(stock, device.paranoid)
            assertEquals("0", device.get(KernelControl.REQUEST_KEY))
        }
    }

    @Test fun a_device_that_was_already_hardened_stays_hardened_after_restore() {
        val device = Device(paranoid = 3)
        val kernel = control(device)
        val prior = kernel.snapshot()!!
        assertEquals("0,3", prior)
        kernel.enforce()
        assertTrue(kernel.restore(prior))
        assertEquals(3, device.paranoid)
    }

    @Test fun re_asserting_does_not_overwrite_the_recorded_prior_value() {
        val device = Device(paranoid = -1)
        val kernel = control(device)
        val prior = kernel.snapshot()!!
        kernel.enforce()
        kernel.enforce()                                   // drift re-assert, now reading 3
        assertEquals("-1", device.get(KernelControl.PRIOR_PERF_KEY))
        kernel.restore(prior)
        assertEquals(-1, device.paranoid)
    }

    @Test fun if_init_never_reacts_enforce_reports_failure() {
        val device = Device(paranoid = -1, initReacts = false)
        assertFalse(control(device).enforce())
    }

    @Test fun an_os_without_the_rc_file_is_unavailable_and_untouched() {
        val device = Device(paranoid = -1, hook = false)
        val kernel = control(device)
        assertFalse(kernel.available())
        assertNull(kernel.snapshot())
    }

    @Test fun an_unreadable_sysctl_means_unavailable() {
        assertFalse(control(Device(paranoid = null)).available())
    }
}
