package com.forrestlasiter.umbra.ui

import android.provider.Settings

/**
 * For an `advisory` capability the app can't enforce, the honest next-best thing
 * is to take the user straight to the OS setting that controls it. This maps a
 * capability token to the Settings action to launch. Kept as pure strings so the
 * mapping is unit-testable without an Android runtime.
 */
object AdvisoryLinks {

    /** The Settings.ACTION_* to open for a capability, or null for none. */
    fun settingsActionFor(capability: String): String? = when (capability) {
        "mac" -> Settings.ACTION_WIFI_SETTINGS               // per-network randomized MAC
        "ipv6_privacy" -> Settings.ACTION_WIFI_SETTINGS
        "hostname" -> Settings.ACTION_DEVICE_INFO_SETTINGS   // device name
        "discovery" -> Settings.ACTION_WIRELESS_SETTINGS
        "bluetooth_off" -> Settings.ACTION_BLUETOOTH_SETTINGS
        "webcam_off" -> Settings.ACTION_PRIVACY_SETTINGS     // camera kill-switch (Android 12+)
        else -> null
    }

    fun hasLink(capability: String): Boolean = settingsActionFor(capability) != null
}
