package com.forrestlasiter.umbra.system

import android.content.Context
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
}

/** Orbot, as seen through PackageManager and ConnectivityManager. */
class OrbotProvider(private val context: Context) : TorProvider {

    override val packageName = OrbotHelper.ORBOT_PACKAGE

    override val installed: Boolean get() = OrbotHelper.isInstalled(context)
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
        if (slot.pinnedTo(provider.packageName) == true) {
            // A re-assert (after a reboot, say). Android is already starting or
            // running the Tor app's VPN; pinning again would restart it and drop
            // every open connection. Give it time, and only if it stays down
            // pin again to make Android start it afresh.
            if (await { vpnUp }) return true
            slot.pin(provider.packageName)
            return isEnforced() == true
        }
        if (!slot.claim()) return false
        // Pinning is the whole action: Android starts the Tor app's VPN itself,
        // and from this call on nothing leaves outside it.
        if (!slot.pin(provider.packageName)) return false
        // Tor needs a while to connect. Wait, so that "enforced" is only ever
        // reported for a VPN that is really up.
        await { vpnUp }
        return isEnforced() == true
    }

    override fun restore(prior: String): Boolean = slot.release(provider.packageName)

    override fun isEnforced(): Boolean? {
        val pinned = slot.pinnedTo(provider.packageName) ?: return null
        return pinned && vpnUp
    }

    /** Is the Tor app's own VPN established right now? */
    private val vpnUp: Boolean get() = slot.activeVpnApp() == provider.packageName

    override fun diagnostic(): String {
        val setting = slot.current()
        val hint = if (slot.pinnedTo(provider.packageName) == true && !vpnUp)
            "; Tor has not connected yet, so traffic is blocked until it does" else ""
        return "tor vpn up=$vpnUp, always-on app=${setting?.first}, lockdown=${setting?.second}$hint"
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
