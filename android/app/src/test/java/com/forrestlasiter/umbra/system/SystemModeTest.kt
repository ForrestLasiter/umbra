package com.forrestlasiter.umbra.system

import com.forrestlasiter.umbra.core.CoreSpec
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The system/ordinary decision must fail SAFE: anything short of every required
 * permission means "ordinary app", so the UI can never claim a system control it
 * does not hold.
 */
class SystemModeTest {

    @Test fun all_permissions_granted_means_system_build() {
        assertEquals(
            CoreSpec.PLATFORM_ANDROID_SYSTEM,
            SystemMode.platformFor(SystemMode.REQUIRED_PERMISSIONS),
        )
    }

    @Test fun no_permissions_means_ordinary_app() {
        assertEquals(CoreSpec.PLATFORM_ANDROID, SystemMode.platformFor(emptySet()))
    }

    @Test fun one_missing_permission_means_ordinary_app() {
        // e.g. WRITE_SECURE_SETTINGS handed out over adb, but nothing else.
        SystemMode.REQUIRED_PERMISSIONS.forEach { missing ->
            assertEquals(
                CoreSpec.PLATFORM_ANDROID,
                SystemMode.platformFor(SystemMode.REQUIRED_PERMISSIONS - missing),
            )
        }
    }
}
