package com.forrestlasiter.umbra.system

/**
 * One thing the OS build can actually change, tied to one capability token from
 * the core spec (e.g. "bluetooth_off").
 *
 * This is the phone's version of a control in the Linux modules, and it keeps
 * the same three duties:
 *
 *   snapshot()  read the state as it is NOW, as plain data
 *   enforce()   make the capability true
 *   restore()   put back exactly what snapshot() recorded
 *
 * The rule that makes leaving a posture trustworthy is "snapshot before mutate":
 * PostureApplier always stores snapshot() before it calls enforce(), and restore
 * only ever replays that stored value. Nothing here guesses what "normal" was.
 *
 * A snapshot is an opaque String on purpose. It is data, not code: it can sit in
 * storage across a reboot or an app update and still be replayed.
 */
interface SystemControl {

    /** The capability token this control satisfies. */
    val capability: String

    /**
     * Can this control work on THIS OS build at all? Most controls only need a
     * permission, which SystemMode has already checked. A few need the OS to ship
     * a helper (the packet-filter service, for example); an OS that integrated
     * Umbra without it must show the capability as unavailable, not as enforced.
     */
    fun available(): Boolean = true

    /**
     * Why the control is unavailable, in words the user can act on, or null when
     * it is available. The default covers the usual case (the OS build lacks a
     * helper); a control with a fixable cause, such as a missing config, says so.
     */
    fun unavailableReason(): String? =
        if (available()) null else "this OS build does not include what Umbra needs to enforce it"

    /** What the control last observed, for the log when something fails. */
    fun diagnostic(): String? = null

    /** The current state, or null if it cannot be read (then nothing is changed). */
    fun snapshot(): String?

    /** Make the capability true. Returns false if the OS refused. */
    fun enforce(): Boolean

    /** Replay a value previously returned by [snapshot]. Returns false on failure. */
    fun restore(prior: String): Boolean

    /** Is the capability true right now? null when it cannot be measured. */
    fun isEnforced(): Boolean?
}
