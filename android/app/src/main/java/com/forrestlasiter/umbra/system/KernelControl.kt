package com.forrestlasiter.umbra.system

import java.io.File

/**
 * kernel -- "Apply kernel hardening (restricted pointers/dmesg/ptrace, full ASLR)."
 *
 * On Linux, Umbra sets a handful of sysctls directly. On Android it cannot:
 * SELinux lets ONLY init read or write the security-sensitive ones
 * (kptr_restrict, randomize_va_space, suid_dumpable). No app and no other
 * service may even look at them, whatever key it is signed with. So this control
 * asks init to do it, through a property that the OS's umbra-kernel.rc reacts to
 * (android/os-integration/).
 *
 * How it stays honest when it cannot read most of what it set: one sysctl in the
 * same group, kernel.perf_event_paranoid, IS readable by apps. init sets it in
 * the same action as the others, so reading it back as 3 proves the action ran.
 * enforce() reports success only after seeing that.
 *
 * What Android does not need from us: dmesg and ptrace are already denied to
 * every app by SELinux, with or without sysctls. And the Linux build's
 * reverse-path filter is deliberately left alone, because Android's
 * multi-network routing depends on it being off.
 *
 * Restore: the three init-only values are the ones Android itself sets at every
 * boot, so re-asserting them changes nothing that needs undoing. The perf
 * lockdown is the one real change, and its prior state is recorded and put back.
 */
class KernelControl(
    private val props: PropertyStore = OsProperties,
    private val perfParanoid: () -> Int? = ::readPerfParanoid,
    private val settle: () -> Unit = { Thread.sleep(NetHookControl.POLL_MS) },
) : SystemControl {

    override val capability = "kernel"

    /** The OS's .rc file announces itself; without it nothing would react. */
    override fun available(): Boolean = props.get(HOOK_KEY) == ON && perfParanoid() != null

    /** "<was the request on>,<was perf hardened>", e.g. "0,0". */
    override fun snapshot(): String? {
        if (!available()) return null
        return "${requested()},${perfHardened() ?: return null}"
    }

    override fun enforce(): Boolean {
        // First time only: tell init what perf hardening to go back to. On a
        // re-assert (already requested) the recorded value must not be
        // overwritten with the hardened state we created.
        if (requested() != ON) {
            val prior = perfHardened() ?: return false
            if (!props.set(PRIOR_PERF_KEY, prior)) return false
        }
        if (!props.set(REQUEST_KEY, ON)) return false
        return waitFor { perfHardened() == ON }
    }

    override fun restore(prior: String): Boolean {
        val (wasRequested, wasPerfHardened) = prior.split(',').let {
            if (it.size != 2) return false
            it[0] to it[1]
        }
        if (wasRequested == ON) return true          // it was already ours to hold
        if (!props.set(PRIOR_PERF_KEY, wasPerfHardened)) return false
        if (!props.set(REQUEST_KEY, OFF)) return false
        return waitFor { perfHardened() == wasPerfHardened }
    }

    override fun isEnforced(): Boolean? = perfHardened()?.let { it == ON }

    override fun diagnostic(): String =
        "kernel.perf_event_paranoid is ${perfParanoid()}; expected $HARDENED_PARANOID after init hardened"

    private fun requested(): String = if (props.get(REQUEST_KEY) == ON) ON else OFF

    /** "1" when perf events are locked down, "0" when not, null if unreadable. */
    private fun perfHardened(): String? =
        perfParanoid()?.let { if (it >= HARDENED_PARANOID) ON else OFF }

    private fun waitFor(condition: () -> Boolean): Boolean {
        repeat(ATTEMPTS) {
            if (condition()) return true
            settle()
        }
        return condition()
    }

    companion object {
        const val HOOK_KEY = "umbra.kernel.hook"
        const val REQUEST_KEY = "persist.umbra.kernel.harden"
        const val PRIOR_PERF_KEY = "persist.umbra.kernel.prior_perf_harden"
        const val ON = "1"
        const val OFF = "0"
        const val HARDENED_PARANOID = 3
        const val ATTEMPTS = 30

        /** The one hardening sysctl SELinux lets an app read. */
        fun readPerfParanoid(): Int? = try {
            File("/proc/sys/kernel/perf_event_paranoid").readText().trim().toIntOrNull()
        } catch (e: Exception) {
            null
        }
    }
}
