package com.forrestlasiter.umbra.system

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.Context
import android.net.wifi.WifiManager
import android.os.UserManager
import android.provider.Settings
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.function.IntConsumer

/*
 * The concrete system controls. Each one is small on purpose: read a value, set a
 * value, put a value back.
 *
 * Why some calls go through reflection: this same source is compiled twice --
 * by Gradle against the PUBLIC Android SDK (the normal app, and CI), and inside
 * an OS build. Calls that exist only in the system API cannot be written directly
 * or the Gradle build would not compile. Reflection lets one file serve both. On
 * a normal install these controls are never constructed (see SystemMode), and a
 * platform-signed app is exempt from the hidden-API blocklist, so the lookups
 * succeed exactly where they are used.
 */

/**
 * mac -- "Randomize the Wi-Fi MAC so the hardware address is not a tracker."
 *
 * Android already uses a random MAC per network, but by default it keeps the SAME
 * random MAC for a given network forever, so that network can still recognise the
 * phone on every visit. This flag switches Wi-Fi to non-persistent randomization:
 * a fresh address per connection. It applies to every network that randomizes
 * (the default); a network the user explicitly set to "use device MAC" is left
 * as they chose.
 */
class MacControl(context: Context) : SystemControl {

    override val capability = "mac"
    private val resolver = context.contentResolver

    override fun snapshot(): String = Settings.Global.getString(resolver, KEY) ?: UNSET

    override fun enforce(): Boolean = Settings.Global.putInt(resolver, KEY, 1)

    // An absent key and "0" behave the same, but restore puts back precisely what
    // was there -- writing null deletes the key again.
    override fun restore(prior: String): Boolean =
        Settings.Global.putString(resolver, KEY, if (prior == UNSET) null else prior)

    override fun isEnforced(): Boolean = Settings.Global.getInt(resolver, KEY, 0) == 1

    private companion object {
        // Read by the Wi-Fi service (WifiConfigManager); the same switch as the
        // "Wi-Fi non-persistent MAC randomization" developer option.
        const val KEY = "non_persistent_mac_randomization_force_enabled"
        const val UNSET = "unset"
    }
}

/**
 * hostname -- "Do not broadcast a stable hostname over DHCP."
 *
 * When a phone joins Wi-Fi it can send its device name in the DHCP request, where
 * the router (and anyone reading its lease table) sees it. Android 15 added a
 * system-wide restriction that suppresses the name on open and/or secured
 * networks; this control sets both bits.
 */
class HostnameControl(context: Context) : SystemControl {

    override val capability = "hostname"
    private val wifi: WifiManager? = context.getSystemService(WifiManager::class.java)

    override fun snapshot(): String? = query()?.toString()

    override fun enforce(): Boolean = set(RESTRICT_ALL)

    override fun restore(prior: String): Boolean = prior.toIntOrNull()?.let { set(it) } ?: false

    override fun isEnforced(): Boolean? = query()?.let { it and RESTRICT_ALL == RESTRICT_ALL }

    private fun set(restriction: Int): Boolean {
        val manager = wifi ?: return false
        return try {
            WifiManager::class.java
                .getMethod("setSendDhcpHostnameRestriction", Int::class.javaPrimitiveType)
                .invoke(manager, restriction)
            true
        } catch (e: ReflectiveOperationException) {
            false   // older Android, or not a system build
        }
    }

    /**
     * The getter is asynchronous (it answers through a callback), but a snapshot
     * has to be taken before the change, so wait briefly for the answer. The
     * callback arrives on a binder thread, so waiting here cannot deadlock.
     */
    private fun query(): Int? {
        val manager = wifi ?: return null
        val latch = CountDownLatch(1)
        var result: Int? = null
        return try {
            WifiManager::class.java
                .getMethod("querySendDhcpHostnameRestriction", Executor::class.java, IntConsumer::class.java)
                .invoke(manager, Executor { it.run() }, IntConsumer { value -> result = value; latch.countDown() })
            if (latch.await(QUERY_TIMEOUT_MS, TimeUnit.MILLISECONDS)) result else null
        } catch (e: ReflectiveOperationException) {
            null
        }
    }

    private companion object {
        // WifiManager.FLAG_SEND_DHCP_HOSTNAME_RESTRICTION_OPEN | _SECURE
        const val RESTRICT_ALL = (1 shl 0) or (1 shl 1)
        const val QUERY_TIMEOUT_MS = 2000L
    }
}

/**
 * webcam_off -- "Disable the camera at the device level."
 *
 * Linux unloads the camera's kernel module. A phone cannot do that, but Android
 * has a user restriction, "no_camera", that the OS itself enforces: while it is
 * set, the camera app-op is denied for EVERY app, so nothing can open any camera.
 * The restriction is stored by the system, so it survives a reboot and does not
 * depend on Umbra's process staying alive -- which is why this was chosen over
 * the alternatives that are either reserved for other system roles or last only
 * as long as the process that set them.
 *
 * If something else (a work-profile admin, say) had already restricted the
 * camera, we record that and never touch it: enforce has nothing to do, and
 * restore must not lift a restriction that was not ours.
 */
class CameraControl(context: Context) : SystemControl {

    override val capability = "webcam_off"
    private val users: UserManager? = context.getSystemService(UserManager::class.java)

    override fun snapshot(): String? = restricted()?.let { if (it) RESTRICTED else ALLOWED }

    override fun enforce(): Boolean = when (restricted()) {
        null -> false
        true -> true                  // already off; nothing to change
        false -> set(true)
    }

    override fun restore(prior: String): Boolean =
        if (prior == ALLOWED) set(false) else true

    override fun isEnforced(): Boolean? = restricted()

    private fun restricted(): Boolean? = users?.userRestrictions?.getBoolean(NO_CAMERA)

    @Suppress("DEPRECATION")   // deprecated in favour of device-admin APIs, which need an admin; a system app uses this
    private fun set(value: Boolean): Boolean {
        val manager = users ?: return false
        return try {
            manager.setUserRestriction(NO_CAMERA, value)
            true
        } catch (e: SecurityException) {
            false   // not a system build
        }
    }

    private companion object {
        const val NO_CAMERA = "no_camera"   // UserManager.DISALLOW_CAMERA (hidden constant)
        const val RESTRICTED = "restricted"
        const val ALLOWED = "allowed"
    }
}

/**
 * bluetooth_off -- "Keep the Bluetooth radio off."
 *
 * Since Android 13 an ordinary app may not switch the radio; a privileged one
 * may. Restore turns Bluetooth back on only if it was on when the posture began.
 * A device with no Bluetooth radio has nothing to silence, which counts as
 * already enforced (the same rule the Linux rfkill control follows).
 */
class BluetoothControl(context: Context) : SystemControl {

    override val capability = "bluetooth_off"
    private val adapter: BluetoothAdapter? =
        context.getSystemService(BluetoothManager::class.java)?.adapter

    override fun snapshot(): String = when {
        adapter == null -> ABSENT
        adapter.isEnabled -> ON
        else -> OFF
    }

    @Suppress("DEPRECATION", "MissingPermission")   // deprecated for ordinary apps; this is not one
    override fun enforce(): Boolean {
        val radio = adapter ?: return true
        return if (radio.isEnabled) radio.disable() else true
    }

    @Suppress("DEPRECATION", "MissingPermission")
    override fun restore(prior: String): Boolean {
        val radio = adapter ?: return true
        return if (prior == ON && !radio.isEnabled) radio.enable() else true
    }

    override fun isEnforced(): Boolean = adapter?.isEnabled != true

    private companion object {
        const val ON = "on"
        const val OFF = "off"
        const val ABSENT = "absent"
    }
}
