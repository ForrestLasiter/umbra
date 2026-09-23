package com.forrestlasiter.umbra.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Settings.ACTION_* are compile-time String constants, so they inline into this
 * test — no Android runtime needed to check the mapping.
 */
class AdvisoryLinksTest {

    @Test fun maps_advisory_capabilities_to_settings_actions() {
        assertEquals("android.settings.WIFI_SETTINGS", AdvisoryLinks.settingsActionFor("mac"))
        assertEquals("android.settings.BLUETOOTH_SETTINGS", AdvisoryLinks.settingsActionFor("bluetooth_off"))
        assertEquals("android.settings.DEVICE_INFO_SETTINGS", AdvisoryLinks.settingsActionFor("hostname"))
    }

    @Test fun capabilities_without_a_setting_return_null() {
        assertNull(AdvisoryLinks.settingsActionFor("firewall"))
        assertNull(AdvisoryLinks.settingsActionFor("telemetry"))
        assertFalse(AdvisoryLinks.hasLink("kernel"))
    }

    @Test fun advisory_ones_have_links() {
        assertTrue(AdvisoryLinks.hasLink("mac"))
        assertTrue(AdvisoryLinks.hasLink("bluetooth_off"))
        assertTrue(AdvisoryLinks.hasLink("webcam_off"))
    }
}
