package com.forrestlasiter.umbra.system

import android.content.Context
import android.util.Log
import com.forrestlasiter.umbra.core.SpecRepository

/**
 * The one entry point the rest of the app uses for system-level enforcement. The
 * tile, the main screen and the shell command all come through here, so there is
 * a single place that decides "is this a system build?" and a single log of what
 * changed.
 */
object SystemPosture {

    private const val TAG = "UmbraPosture"

    /**
     * The controls this build has, in apply order. Radios and identity go last,
     * matching the Linux engine's APPLY_ORDER (raise walls first, radios last).
     */
    private fun controls(context: Context): List<SystemControl> = listOf(
        MacControl(context),
        BluetoothControl(context),
        HostnameControl(context),
    )

    private fun applier(context: Context) =
        PostureApplier(controls(context), PrefsSnapshotStore(context))

    /** The profile the system controls are currently holding, or "normal". */
    fun activeProfile(context: Context): String =
        PrefsSnapshotStore(context).activeProfile ?: PostureApplier.NORMAL

    /**
     * Apply [profile] with the system controls. Returns null -- and changes
     * nothing -- when this is not a system build or the profile does not exist,
     * so a normal install can call this unconditionally.
     */
    fun apply(context: Context, profile: String): List<Outcome>? {
        val app = context.applicationContext
        if (!SystemMode.isSystemBuild(app)) return null
        val spec = SpecRepository(app).load()
        if (profile !in spec.profiles) {
            Log.w(TAG, "unknown profile '$profile'; nothing changed")
            return null
        }
        val outcomes = applier(app).apply(spec, profile, SystemMode.platform(app))
        outcomes.forEach {
            Log.i(TAG, "profile=$profile ${it.capability}: ${it.change}${if (it.ok) "" else " FAILED"}")
        }
        return outcomes
    }

    /** A one-line, user-facing summary of an apply, honest about failures. */
    fun summarize(profile: String, outcomes: List<Outcome>): String {
        val failed = outcomes.filter { !it.ok }.map { it.capability }
        val enforced = outcomes.count { it.ok && (it.change == Change.ENFORCED || it.change == Change.KEPT) }
        return when {
            failed.isNotEmpty() -> "$profile: could not change ${failed.joinToString()}"
            profile == PostureApplier.NORMAL -> "Back to normal: system settings restored."
            else -> "$profile: $enforced system control(s) enforced."
        }
    }
}
