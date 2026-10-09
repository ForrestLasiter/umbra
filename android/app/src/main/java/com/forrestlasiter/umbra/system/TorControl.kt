package com.forrestlasiter.umbra.system

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.forrestlasiter.umbra.tor.OrbotHelper

/*
 * tor -- "Route all traffic through Tor with an egress killswitch."
 *
 * Umbra does not re-implement Tor. The Tor Project's own app (Orbot) carries the
 * traffic through its VPN mode; what the ordinary app cannot do is make that
 * stick -- the user must start Orbot, tap through its VPN consent, and nothing
 * stops traffic leaving when Orbot is not running.
 *
 * Built into the OS, Umbra closes that gap with the same mechanism as the
 * WireGuard control: it authorizes the Tor app as a VPN (no dialog) and pins it
 * as Android's ALWAYS-ON VPN with LOCKDOWN. Android then starts the Tor app's
 * VPN by itself, restarts it after a reboot, and drops every packet that would
 * leave outside it. The killswitch is Android's own.
 *
 * "Enforced" means: lockdown reads back as pinned to the Tor app AND that app's
 * VPN is up. It does not prove a circuit is built or what the exit address is;
 * while Tor is still connecting the phone is offline, not leaking.
 */

/** The app that provides Tor. An interface so the control is testable. */
interface TorProvider {
    val packageName: String
    val installed: Boolean

    /** Is this app's VPN up right now? */
    val vpnUp: Boolean
}

/** Orbot, as seen through PackageManager and ConnectivityManager. */
class OrbotProvider(private val context: Context) : TorProvider {

    override val packageName = OrbotHelper.ORBOT_PACKAGE

    override val installed: Boolean get() = OrbotHelper.isInstalled(context)

    override val vpnUp: Boolean
        get() {
            val connectivity = context.getSystemService(ConnectivityManager::class.java) ?: return false
            val uid = try {
                context.packageManager.getApplicationInfo(packageName, 0).uid
            } catch (e: Exception) {
                return false
            }
            @Suppress("DEPRECATION")    // allNetworks: the callback API cannot answer "right now"
            return connectivity.allNetworks.any { network ->
                val caps = connectivity.getNetworkCapabilities(network)
                caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) && caps.ownerUid == uid
            }
        }
}

class TorControl(
    private val slot: VpnSlot,
    private val provider: TorProvider,
    /** Wait for the condition to become true; returns whether it did. */
    private val await: (() -> Boolean) -> Boolean = { pollUntil(it) },
) : SystemControl {

    constructor(context: Context, slot: VpnSlot) : this(slot, OrbotProvider(context))

    override val capability = "tor"

    override fun available(): Boolean = unavailableReason() == null

    override fun unavailableReason(): String? = when {
        !provider.installed -> "Orbot, the app that provides Tor, is not installed"
        slot.current() == null -> "this OS build does not let Umbra manage the always-on VPN"
        else -> null
    }

    /** The slot as it is now. Informational: the shared [VpnSlot] ledger is what restore uses. */
    override fun snapshot(): String? {
        if (!available()) return null
        val (app, lockdown) = slot.current() ?: return null
        return "${app.orEmpty()}|$lockdown"
    }

    override fun enforce(): Boolean {
        // Already holding (a re-assert): leave it be. Pinning again would make
        // Android restart the Tor app's VPN and drop every open connection.
        if (isEnforced() == true) return true
        if (!slot.claim()) return false
        // Pinning is the whole action: Android starts the Tor app's VPN itself,
        // and from this call on nothing leaves outside it.
        if (!slot.pin(provider.packageName)) return false
        // Tor needs a while to connect. Wait, so that "enforced" is only ever
        // reported for a VPN that is really up.
        await { provider.vpnUp }
        return isEnforced() == true
    }

    override fun restore(prior: String): Boolean = slot.release(provider.packageName)

    override fun isEnforced(): Boolean? {
        val pinned = slot.pinnedTo(provider.packageName) ?: return null
        return pinned && provider.vpnUp
    }

    override fun diagnostic(): String {
        val setting = slot.current()
        val hint = if (slot.pinnedTo(provider.packageName) == true && !provider.vpnUp)
            "; Tor has not connected yet, so traffic is blocked until it does" else ""
        return "tor vpn up=${provider.vpnUp}, always-on app=${setting?.first}, lockdown=${setting?.second}$hint"
    }

    private companion object {
        // Under a minute: a command-line apply holds a broadcast open while it waits.
        const val WAIT_MS = 40_000L
        const val STEP_MS = 1_000L

        fun pollUntil(condition: () -> Boolean): Boolean {
            val deadline = System.currentTimeMillis() + WAIT_MS
            while (System.currentTimeMillis() < deadline) {
                if (condition()) return true
                try { Thread.sleep(STEP_MS) } catch (e: InterruptedException) { return false }
            }
            return condition()
        }
    }
}
