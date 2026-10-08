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
 * same group, kernel.perf_event_paranoid, IS readable by apps. init sets it to 3
 * in the same action as the others, so reading 3 back proves the action ran.
 * enforce() reports success only after seeing that.
 *
 * What Android does not need from us: dmesg and ptrace are already denied to
 * every app by SELinux, with or without sysctls. And the Linux build's
 * reverse-path filter is deliberately left alone, because Android's
 * multi-network routing depends on it being off.
 *
 * Restore: the three init-only values are the ones Android itself sets at every
 * boot, so re-asserting them changes nothing that needs undoing.
 * perf_event_paranoid is the one real change (modern Android leaves it at -1 and
 * relies on SELinux alone), so its prior value is recorded and put back.
 */
class KernelControl(
    private val props: PropertyStore = OsProperties,
    private val perfParanoid: () -> Int? = ::readPerfParanoid,
    private val settle: () -> Unit = { Thread.sleep(NetHookControl.POLL_MS) },
) : SystemControl {

    override val capability = "kernel"

    /** The OS's .rc file announces itself; without it nothing would react. */
    override fun available(): Boolean = props.get(HOOK_KEY) == ON && perfParanoid() != null

    /** "<was the request on>,<perf_event_paranoid then>", e.g. "0,-1". */
    override fun snapshot(): String? {
        if (!available()) return null
        return "${requested()},${perfParanoid() ?: return null}"
    }

    override fun enforce(): Boolean {
        // First time only: tell init what value to go back to. On a re-assert
        // (already requested) the recorded value must not be overwritten with
        // the hardened one we created.
        if (requested() != ON) {
            val prior = perfParanoid() ?: return false
            if (!props.set(PRIOR_PERF_KEY, prior.toString())) return false
        }
        if (!props.set(REQUEST_KEY, ON)) return false
        return waitFor { perfParanoid() == HARDENED_PARANOID }
    }

    override fun restore(prior: String): Boolean {
        val parts = prior.split(',')
        if (parts.size != 2) return false
        val wasRequested = parts[0]
        val priorParanoid = parts[1].toIntOrNull() ?: return false
        if (wasRequested == ON) return true          // it was already ours to hold
        if (!props.set(PRIOR_PERF_KEY, priorParanoid.toString())) return false
        if (!props.set(REQUEST_KEY, OFF)) return false
        return waitFor { perfParanoid() == priorParanoid }
    }

    override fun isEnforced(): Boolean? = perfParanoid()?.let { it >= HARDENED_PARANOID }

    override fun diagnostic(): String =
        "kernel.perf_event_paranoid is ${perfParanoid()}; expected $HARDENED_PARANOID after init hardened"

    private fun requested(): String = if (props.get(REQUEST_KEY) == ON) ON else OFF

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
        const val PRIOR_PERF_KEY = "persist.umbra.kernel.prior_perf_paranoid"
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
