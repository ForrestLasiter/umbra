package com.forrestlasiter.umbra.system

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.forrestlasiter.umbra.core.SpecRepository
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

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
        KernelControl(),
        TelemetryControl(canary = canaryDomain(context)),
        FirewallControl(),
        DiscoveryControl(),
        WireGuardControl(context),
        MacControl(context),
        BluetoothControl(context),
        CameraControl(context),
        HostnameControl(context),
    )

    /**
     * Capabilities the matrix promises on a system build but that this particular
     * OS cannot deliver. Empty on a normal install (nothing is promised there).
     */
    fun unavailable(context: Context): Map<String, String> {
        val app = context.applicationContext
        if (!SystemMode.isSystemBuild(app)) return emptyMap()
        return controls(app).mapNotNull { control ->
            control.unavailableReason()?.let { control.capability to it }
        }.toMap()
    }

    /**
     * One background thread for every posture change.
     *
     * A posture must never be applied on the main thread: controls wait for the
     * OS to confirm (a property read-back, a DNS lookup), and the WireGuard
     * library starts its VPN service and waits for it, which deadlocks if the
     * main thread is the one waiting. A SINGLE thread also means two applies can
     * never interleave -- the second simply runs after the first.
     */
    private val worker: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "umbra-posture").apply { isDaemon = true }
    }
    private val mainThread = Handler(Looper.getMainLooper())

    /** Run [work] on the posture thread. */
    fun inBackground(work: () -> Unit) { worker.execute(work) }

    /**
     * Apply [profile] off the main thread, then hand the result to [done] back on
     * the main thread (where UI may be touched).
     */
    fun applyInBackground(context: Context, profile: String, done: (List<Outcome>?) -> Unit = {}) {
        val app = context.applicationContext
        inBackground {
            val outcomes = try {
                apply(app, profile)
            } catch (e: Exception) {
                Log.e(TAG, "applying '$profile' failed", e)
                null
            }
            mainThread.post { done(outcomes) }
        }
    }

    /**
     * Re-assert the posture the phone is already in. Used when the OS restarts
     * our always-on VPN (after a reboot, or if the process was killed): the
     * settings survived, the tunnel did not, so run the active profile again.
     */
    fun reassertInBackground(context: Context) {
        val profile = activeProfile(context)
        if (profile != PostureApplier.NORMAL) applyInBackground(context, profile)
    }

    /**
     * A blocklisted domain the telemetry control resolves to prove the sinkhole
     * works. Taken from the bundled spec so it is always a name the OS's hosts
     * file (generated from the same lists) contains. Null if the spec has none.
     */
    private fun canaryDomain(context: Context): String? = try {
        SpecRepository(context).load().telemetryBlocklists.values.flatten().minOrNull()
    } catch (e: Exception) {
        null
    }

    /** The profile the system controls are currently holding, or "normal". */
    fun activeProfile(context: Context): String =
        PrefsSnapshotStore(context).activeProfile ?: PostureApplier.NORMAL

    /**
     * Apply [profile] with the system controls. Returns null -- and changes
     * nothing -- when this is not a system build or the profile does not exist,
     * so a normal install can call this unconditionally.
     *
     * Blocks while controls confirm. Call it from [inBackground] (or use
     * [applyInBackground]); never from the main thread.
     */
    fun apply(context: Context, profile: String): List<Outcome>? {
        val app = context.applicationContext
        if (!SystemMode.isSystemBuild(app)) return null
        val spec = SpecRepository(app).load()
        if (profile !in spec.profiles) {
            Log.w(TAG, "unknown profile '$profile'; nothing changed")
            return null
        }
        val controls = controls(app)
        val outcomes = PostureApplier(controls, PrefsSnapshotStore(app))
            .apply(spec, profile, SystemMode.platform(app))
        outcomes.forEach { outcome ->
            Log.i(TAG, "profile=$profile ${outcome.capability}: ${outcome.change}${if (outcome.ok) "" else " FAILED"}")
            // A failure with no reason is no use to anyone reading the log.
            if (!outcome.ok) {
                controls.firstOrNull { it.capability == outcome.capability }?.diagnostic()
                    ?.let { Log.w(TAG, "  ${outcome.capability}: $it") }
            }
        }
        return outcomes
    }

    /**
     * Measure the posture the phone is in, without changing anything: for each
     * capability the active profile enforces here, ask its control whether it is
     * actually in force at this moment. This is the phone's version of the Linux
     * build's audit -- what was applied can drift (someone flips a setting, a
     * tunnel drops), and the only honest status is a fresh measurement.
     *
     * Returns null when this is not a system build. Blocks; call off the main thread.
     */
    fun audit(context: Context): List<AuditItem>? {
        val app = context.applicationContext
        if (!SystemMode.isSystemBuild(app)) return null
        val spec = SpecRepository(app).load()
        val wanted = PostureApplier.wantedFor(spec, activeProfile(app), SystemMode.platform(app))
        return controls(app).filter { it.capability in wanted }.map { control ->
            val reason = control.unavailableReason()
            if (reason != null) AuditItem(control.capability, holding = null, note = reason)
            else {
                val holding = control.isEnforced()
                AuditItem(control.capability, holding, if (holding == true) null else control.diagnostic())
            }
        }
    }

    // The wording of results lives in PostureReport (pure, unit-tested); these
    // keep the call sites short.
    fun summarize(profile: String, outcomes: List<Outcome>): String =
        PostureReport.summarize(profile, outcomes)

    fun summarizeAudit(profile: String, items: List<AuditItem>): String =
        PostureReport.summarizeAudit(profile, items)
}
