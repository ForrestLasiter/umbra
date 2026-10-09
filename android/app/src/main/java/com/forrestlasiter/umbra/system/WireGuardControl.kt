package com.forrestlasiter.umbra.system

import android.content.Context
import android.net.VpnManager
import android.os.Process
import com.forrestlasiter.umbra.vpn.Tunnels
import com.forrestlasiter.umbra.wg.WgConfigStore

/*
 * wireguard -- "Route all traffic through a WireGuard tunnel with an egress
 * killswitch."
 *
 * The ordinary app can bring a WireGuard tunnel up, but only after the user taps
 * through Android's VPN consent dialog, and it has no say over what happens to
 * traffic when the tunnel is down. Built into the OS, Umbra can do both halves
 * properly:
 *
 *   1. authorize itself as the VPN app (no dialog),
 *   2. bring the tunnel up,
 *   3. pin itself as Android's ALWAYS-ON VPN with LOCKDOWN.
 *
 * Step 3 is the killswitch, and it is Android's own, not ours: with lockdown on,
 * the OS drops every packet that would leave outside the VPN, including while
 * the tunnel is down, reconnecting, or after a reboot before it is back. If the
 * endpoint is unreachable the phone has no connectivity -- but it does not leak.
 *
 * "Enforced" therefore means: the tunnel interface is up AND lockdown reads back
 * as on for this app. It does not promise the far end is answering; that is the
 * endpoint's job, and the fail-closed lockdown is what makes its absence safe.
 */

/** Android's always-on VPN setting. An interface so the control is testable. */
interface AlwaysOnVpn {
    /** Let [packageName] run a VPN without the consent dialog. */
    fun authorize(packageName: String): Boolean

    /** The current always-on app (or null) and whether lockdown is on. Null if unreadable. */
    fun current(): Pair<String?, Boolean>?

    /** Set (or with null, clear) the always-on app and its lockdown flag. */
    fun set(packageName: String?, lockdown: Boolean): Boolean
}

/** The tunnel itself. An interface so the control is testable. */
interface WireGuardTunnel {
    /** Is there a real tunnel implementation in this build? */
    val bundled: Boolean
    val isUp: Boolean
    fun up(config: String)
    fun down()
}

/**
 * The real always-on setting, through VpnManager's hidden methods (reflection
 * for the usual reason: the Gradle build compiles against the public SDK).
 */
class SystemAlwaysOnVpn(context: Context) : AlwaysOnVpn {

    private val manager: VpnManager? = context.getSystemService(VpnManager::class.java)
    private val userId: Int = Process.myUserHandle().hashCode()     // UserHandle.getIdentifier()

    override fun authorize(packageName: String): Boolean = call(
        "setVpnPackageAuthorization",
        arrayOf(String::class.java, Int::class.javaPrimitiveType!!, Int::class.javaPrimitiveType!!),
        packageName, userId, TYPE_VPN_SERVICE,
    ) != FAILED

    override fun current(): Pair<String?, Boolean>? {
        val app = call("getAlwaysOnVpnPackageForUser", arrayOf(Int::class.javaPrimitiveType!!), userId)
        val lockdown = call("isVpnLockdownEnabled", arrayOf(Int::class.javaPrimitiveType!!), userId)
        if (app === FAILED || lockdown === FAILED) return null
        return (app as String?) to (lockdown as Boolean)
    }

    override fun set(packageName: String?, lockdown: Boolean): Boolean = call(
        "setAlwaysOnVpnPackageForUser",
        arrayOf(Int::class.javaPrimitiveType!!, String::class.java, Boolean::class.javaPrimitiveType!!, List::class.java),
        userId, packageName, lockdown, null,
    ) == true

    /** Invoke a hidden VpnManager method. Returns [FAILED] if it is missing or refused. */
    private fun call(name: String, types: Array<Class<*>>, vararg args: Any?): Any? {
        val vpn = manager ?: return FAILED
        return try {
            VpnManager::class.java.getMethod(name, *types).invoke(vpn, *args)
        } catch (e: Exception) {
            FAILED
        }
    }

    private companion object {
        const val TYPE_VPN_SERVICE = 1          // VpnManager.TYPE_VPN_SERVICE
        val FAILED = Any()
    }
}

class WireGuardControl(
    private val packageName: String,
    private val alwaysOn: AlwaysOnVpn,
    private val tunnel: WireGuardTunnel,
    private val config: () -> String?,
) : SystemControl {

    constructor(context: Context) : this(
        packageName = context.packageName,
        alwaysOn = SystemAlwaysOnVpn(context),
        tunnel = Tunnels.wireGuard(context),
        config = { WgConfigStore(context).load() },
    )

    override val capability = "wireguard"

    override fun available(): Boolean = unavailableReason() == null

    override fun unavailableReason(): String? = when {
        !tunnel.bundled -> "this OS build does not include a WireGuard tunnel"
        alwaysOn.current() == null -> "this OS build does not let Umbra manage the always-on VPN"
        config() == null -> "no WireGuard config imported yet; import one in the Umbra app"
        else -> null
    }

    /** "<always-on app or empty>|<lockdown>", e.g. "|false" or "com.example.vpn|true". */
    override fun snapshot(): String? {
        if (!available()) return null
        val (app, lockdown) = alwaysOn.current() ?: return null
        return "${app.orEmpty()}|$lockdown"
    }

    override fun enforce(): Boolean {
        val text = config() ?: return false
        if (!alwaysOn.authorize(packageName)) return false
        // Tunnel first, lockdown second: bringing the tunnel up needs no network
        // by itself, and this order never leaves lockdown pointing at nothing.
        if (!tunnel.isUp) {
            try { tunnel.up(text) } catch (e: Exception) { lastError = e.message ?: e.toString(); return false }
        }
        if (!alwaysOn.set(packageName, lockdown = true)) return false
        return isEnforced() == true
    }

    override fun restore(prior: String): Boolean {
        val parts = prior.split('|')
        if (parts.size != 2) return false
        val priorApp = parts[0].ifEmpty { null }
        val priorLockdown = parts[1].toBoolean()
        if (priorApp == packageName && priorLockdown) return true   // already ours before; leave it
        // Lockdown off first, then the tunnel: the other order would strand the
        // phone offline behind a killswitch with no tunnel.
        val settingRestored = alwaysOn.set(priorApp, priorLockdown)
        try { tunnel.down() } catch (e: Exception) { lastError = e.message ?: e.toString() }
        return settingRestored && !tunnel.isUp
    }

    override fun isEnforced(): Boolean? {
        val (app, lockdown) = alwaysOn.current() ?: return null
        return tunnel.isUp && lockdown && app == packageName
    }

    private var lastError: String? = null

    override fun diagnostic(): String {
        val setting = alwaysOn.current()
        return "tunnel up=${tunnel.isUp}, always-on app=${setting?.first}, lockdown=${setting?.second}" +
            (lastError?.let { ", last error: $it" } ?: "")
    }
}
