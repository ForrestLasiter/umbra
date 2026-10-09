package com.forrestlasiter.umbra.system

import com.forrestlasiter.umbra.core.CoreSpec
import com.forrestlasiter.umbra.core.Enforcement

/** What happened to one control during a reconcile. */
enum class Change {
    ENFORCED,    // was off, snapshot taken, now on
    KEPT,        // already part of the posture; re-asserted in case it drifted
    RESTORED,    // no longer wanted; prior state replayed
    UNTOUCHED,   // not wanted and never changed by us
    UNAVAILABLE, // wanted, but this OS build lacks what the control needs
}

/** [note] says why, when there is something the user should know (e.g. why unavailable). */
data class Outcome(val capability: String, val change: Change, val ok: Boolean, val note: String? = null)

/**
 * Reconciles the system controls to a set of wanted capabilities, and unwinds
 * them again. Pure logic: it sees only the SystemControl and SnapshotStore
 * interfaces, so every branch is unit-tested without a phone.
 *
 * The one invariant: **a control is restored if and only if we hold a snapshot
 * for it.** Holding a snapshot means "Umbra changed this and still owes the user
 * their old setting back". That single fact drives all four cases below, and it
 * is why switching straight from one profile to another is safe -- controls the
 * new profile keeps are left alone (snapshot untouched, so `normal` still returns
 * to the ORIGINAL state), and controls it drops are restored.
 */
class PostureApplier(
    private val controls: List<SystemControl>,
    private val store: SnapshotStore,
) {

    /** Bring every control in line with [wanted]. Never throws; reports per control. */
    fun reconcile(wanted: Set<String>): List<Outcome> = controls.map { control ->
        val cap = control.capability
        val prior = store.get(cap)
        when {
            // Wanted but impossible here: change nothing and say so. (If we hold
            // a snapshot from before, fall through and keep/restore as usual --
            // an unavailable control must never strand a setting we changed.)
            cap in wanted && prior == null && !control.available() ->
                Outcome(cap, Change.UNAVAILABLE, ok = true, note = control.unavailableReason())
            cap in wanted && prior == null -> {
                val now = control.snapshot()
                if (now == null) {
                    // Can't read it, so we couldn't put it back. Change nothing.
                    Outcome(cap, Change.ENFORCED, ok = false)
                } else {
                    store.put(cap, now)                 // snapshot BEFORE mutate
                    Outcome(cap, Change.ENFORCED, ok = safely { control.enforce() })
                }
            }
            cap in wanted -> Outcome(cap, Change.KEPT, ok = safely { control.enforce() })
            prior != null -> {
                val ok = safely { control.restore(prior) }
                // Keep the snapshot if the restore failed, so a retry can still
                // put the original value back.
                if (ok) store.remove(cap)
                Outcome(cap, Change.RESTORED, ok)
            }
            else -> Outcome(cap, Change.UNTOUCHED, ok = true)
        }
    }

    /**
     * Apply a named profile: enforce the capabilities it requires that this
     * platform marks ENFORCED *and* that have a control here; restore the rest.
     * "normal" requires nothing, so applying it restores everything.
     */
    fun apply(spec: CoreSpec, profile: String, platform: String): List<Outcome> {
        val outcomes = reconcile(wantedFor(spec, profile, platform))
        // Only forget the posture once it is fully unwound; a half-restored phone
        // must still read as "in a posture" so the user knows to retry.
        val unwound = outcomes.none { it.change == Change.RESTORED && !it.ok }
        store.activeProfile = when {
            profile != NORMAL -> profile
            unwound -> null
            else -> store.activeProfile
        }
        return outcomes
    }

    private fun safely(action: () -> Boolean): Boolean =
        try { action() } catch (e: Exception) { false }

    companion object {
        const val NORMAL = "normal"

        /**
         * The capabilities a profile needs that the system build genuinely
         * enforces. Anything the matrix marks advisory / needs-root / via-tunnel
         * is deliberately left out: those are someone else's job (the tunnel
         * code) or nobody's yet, and must not be reported as done here.
         */
        fun wantedFor(spec: CoreSpec, profile: String, platform: String): Set<String> {
            val requires = spec.profiles[profile]?.requires ?: emptyList()
            return requires.filterTo(mutableSetOf()) {
                spec.support(it, platform).enforcement == Enforcement.ENFORCED
            }
        }
    }
}
