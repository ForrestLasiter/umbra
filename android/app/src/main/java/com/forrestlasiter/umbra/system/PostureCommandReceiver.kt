package com.forrestlasiter.umbra.system

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Applies a profile from the command line, so a system build can be driven and
 * verified without touching the screen:
 *
 *   adb shell am broadcast -n com.forrestlasiter.umbra/.system.PostureCommandReceiver \
 *       -a com.forrestlasiter.umbra.action.APPLY_POSTURE --es profile travel
 *
 * It is exported, so the manifest guards it with android.permission.DUMP -- a
 * permission held by the shell and the system but not by ordinary apps. Another
 * app on the phone therefore cannot use it to change (or drop) the posture.
 *
 * It only drives the system controls. Tunnel postures still need the app, where
 * the user can give VPN consent.
 */
class PostureCommandReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_APPLY) return
        val profile = intent.getStringExtra(EXTRA_PROFILE) ?: PostureApplier.NORMAL
        val outcomes = SystemPosture.apply(context, profile)
        val summary = when (outcomes) {
            null -> "not applied: not a system build, or unknown profile '$profile'"
            else -> SystemPosture.summarize(profile, outcomes)
        }
        Log.i("UmbraPosture", summary)
        // `am broadcast` sends an ordered broadcast and echoes the result data, so
        // the caller sees what happened. A plain broadcast has nowhere to put it.
        if (isOrderedBroadcast) resultData = summary
    }

    companion object {
        const val ACTION_APPLY = "com.forrestlasiter.umbra.action.APPLY_POSTURE"
        const val EXTRA_PROFILE = "profile"
    }
}
