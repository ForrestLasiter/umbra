package com.forrestlasiter.umbra.system

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.forrestlasiter.umbra.wg.WgConfigStore

/**
 * Drives a system build from the command line, so it can be tested and scripted
 * without touching the screen:
 *
 *   adb shell am broadcast -n com.forrestlasiter.umbra/.system.PostureCommandReceiver \
 *       -a com.forrestlasiter.umbra.action.APPLY_POSTURE --es profile travel
 *
 *   adb shell am broadcast -n com.forrestlasiter.umbra/.system.PostureCommandReceiver \
 *       -a com.forrestlasiter.umbra.action.IMPORT_WIREGUARD --es config "$(cat vpn.conf)"
 *
 *   adb shell am broadcast -n com.forrestlasiter.umbra/.system.PostureCommandReceiver \
 *       -a com.forrestlasiter.umbra.action.AUDIT
 *
 * It is exported, so the manifest guards it with android.permission.DUMP -- a
 * permission held by the shell and the system but not by ordinary apps. Another
 * app on the phone therefore cannot use it to change (or drop) the posture, or
 * to swap the tunnel for one of its own.
 */
class PostureCommandReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            ACTION_APPLY -> applyPosture(context, intent)
            ACTION_IMPORT_WIREGUARD -> report(importWireGuard(context, intent))
            ACTION_AUDIT -> audit(context)
        }
    }

    /** Measure the current posture without changing it, and say what is holding. */
    private fun audit(context: Context) {
        val ordered = isOrderedBroadcast
        val pending = goAsync()
        val app = context.applicationContext
        SystemPosture.inBackground {
            val profile = SystemPosture.activeProfile(app)
            val items = try { SystemPosture.audit(app) } catch (e: Exception) { null }
            val summary = if (items == null) "not audited: not a system build"
                          else SystemPosture.summarizeAudit(profile, items)
            Log.i(TAG, summary)
            items?.filter { it.holding != true }?.forEach { Log.w(TAG, "  ${it.capability}: ${it.note}") }
            if (ordered) pending.resultData = summary
            pending.finish()
        }
    }

    private fun applyPosture(context: Context, intent: Intent) {
        val profile = intent.getStringExtra(EXTRA_PROFILE) ?: PostureApplier.NORMAL
        // Applying blocks while controls confirm, so it must not run here on the
        // main thread. goAsync() keeps this broadcast open until the work is done,
        // which is what lets `am broadcast` still print the result.
        val ordered = isOrderedBroadcast        // must be read before goAsync()
        val pending = goAsync()
        SystemPosture.applyInBackground(context, profile) { outcomes ->
            val summary = when (outcomes) {
                null -> "not applied: not a system build, or unknown profile '$profile'"
                else -> SystemPosture.summarize(profile, outcomes)
            }
            Log.i(TAG, summary)
            if (ordered) pending.resultData = summary
            pending.finish()
        }
    }

    /** Store a WireGuard config, exactly as the app's "Import" button would. */
    private fun importWireGuard(context: Context, intent: Intent): String {
        if (!SystemMode.isSystemBuild(context)) return "not imported: not a system build"
        val text = intent.getStringExtra(EXTRA_CONFIG) ?: return "not imported: no config given"
        return try {
            val store = WgConfigStore(context)
            store.save(text)
            "imported WireGuard config (endpoint ${store.summary()?.endpoint})"
        } catch (e: Exception) {
            "not imported: ${e.message}"
        }
    }

    private fun report(summary: String) {
        Log.i(TAG, summary)
        // `am broadcast` sends an ordered broadcast and echoes the result data, so
        // the caller sees what happened. A plain broadcast has nowhere to put it.
        if (isOrderedBroadcast) resultData = summary
    }

    companion object {
        private const val TAG = "UmbraPosture"
        const val ACTION_APPLY = "com.forrestlasiter.umbra.action.APPLY_POSTURE"
        const val ACTION_IMPORT_WIREGUARD = "com.forrestlasiter.umbra.action.IMPORT_WIREGUARD"
        const val ACTION_AUDIT = "com.forrestlasiter.umbra.action.AUDIT"
        const val EXTRA_PROFILE = "profile"
        const val EXTRA_CONFIG = "config"
    }
}
