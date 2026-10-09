package com.forrestlasiter.umbra.system

import android.content.Context
import android.content.pm.PackageManager
import com.forrestlasiter.umbra.core.CoreSpec

/**
 * Is this copy of Umbra a guest on the phone, or part of the OS?
 *
 * The same app can be installed two ways:
 *   - normally (Play/F-Droid/sideload): a sandboxed app whose one real lever is
 *     VPNService. It plans against the spec's `android` platform.
 *   - built into a custom Android OS and signed with that OS's platform key: it
 *     then holds signature-level permissions no ordinary app can get, and plans
 *     against `android_system`.
 *
 * We do not ask "am I a system app?" -- that flag says where the APK lives, not
 * what it may do. We ask the question that actually matters: were the
 * permissions the system controls need really granted? If even one is missing we
 * behave as the ordinary app, so the UI can never show "enforced" for something
 * this install cannot enforce.
 */
object SystemMode {

    /**
     * Every permission a system control relies on. All are signature-level (or
     * privileged), so on a normal install they are declared but never granted.
     */
    val REQUIRED_PERMISSIONS: Set<String> = setOf(
        "android.permission.WRITE_SECURE_SETTINGS",  // MAC randomization flag
        "android.permission.NETWORK_SETTINGS",       // DHCP hostname restriction
        "android.permission.BLUETOOTH_PRIVILEGED",   // turn the radio off without a prompt
        "android.permission.MANAGE_USERS",           // the "no camera" user restriction
        "android.permission.CONTROL_VPN",            // start the tunnel without a consent dialog
        "android.permission.CONTROL_ALWAYS_ON_VPN",  // always-on VPN with lockdown
    )

    /** Pure decision, kept separate from Android so it is unit-testable. */
    fun platformFor(granted: Set<String>): String =
        if (granted.containsAll(REQUIRED_PERMISSIONS)) CoreSpec.PLATFORM_ANDROID_SYSTEM
        else CoreSpec.PLATFORM_ANDROID

    fun grantedPermissions(context: Context): Set<String> =
        REQUIRED_PERMISSIONS.filterTo(mutableSetOf()) {
            context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
        }

    /** The spec platform this install should plan against. */
    fun platform(context: Context): String = platformFor(grantedPermissions(context))

    fun isSystemBuild(context: Context): Boolean =
        platform(context) == CoreSpec.PLATFORM_ANDROID_SYSTEM
}
