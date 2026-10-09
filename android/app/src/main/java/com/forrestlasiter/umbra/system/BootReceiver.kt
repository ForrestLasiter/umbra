package com.forrestlasiter.umbra.system

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.forrestlasiter.umbra.tor.BundledOrbot

/**
 * Re-asserts the posture after the phone restarts.
 *
 * Most of what a posture changes survives a reboot by itself: the packet-filter
 * and kernel requests are persistent properties the OS re-applies during boot,
 * and settings such as the camera restriction are stored by the system. But
 * "most" is not "all", and a posture that is supposed to be active should not
 * depend on that. So once the phone is up, run the active profile again: every
 * control that is already in place is simply confirmed, and anything that did
 * not come back is put back.
 *
 * It is the phone's counterpart to the Linux build re-applying on network-up.
 * On a normal install there are no system controls and this does nothing.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (!SystemMode.isSystemBuild(context)) return
        // First boot of an OS image that carries Orbot: install it, so Tor is
        // there before the user ever asks for it.
        BundledOrbot.installOnce(context)
        // goAsync keeps the process alive until the re-assert has finished.
        val pending = goAsync()
        val profile = SystemPosture.activeProfile(context)
        if (profile == PostureApplier.NORMAL) { pending.finish(); return }
        SystemPosture.applyInBackground(context, profile) { pending.finish() }
    }
}
