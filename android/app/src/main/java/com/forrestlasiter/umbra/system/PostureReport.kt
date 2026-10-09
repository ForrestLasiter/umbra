package com.forrestlasiter.umbra.system

/** One capability's answer to "is this true on the phone RIGHT NOW?". */
data class AuditItem(
    val capability: String,
    /** true = in force, false = drifted, null = could not be enforced or measured. */
    val holding: Boolean?,
    val note: String? = null,
)

/**
 * How results are worded for the user. Kept apart from SystemPosture so it is
 * plain Kotlin with no Android in it, and every sentence can be unit-tested.
 *
 * The rule for all of it: never round up. A failure is named, something that
 * could not be enforced is named with its reason, and "verified" counts only
 * what was measured and found true.
 */
object PostureReport {

    /** A one-line summary of an apply, honest about failures. */
    fun summarize(profile: String, outcomes: List<Outcome>): String {
        val failed = outcomes.filter { !it.ok }.map { it.capability }
        val enforced = outcomes.count { it.ok && (it.change == Change.ENFORCED || it.change == Change.KEPT) }
        // Say WHY each one is missing: "no WireGuard config imported" is something
        // the user can fix, "this OS build lacks it" is not.
        val missing = outcomes.filter { it.change == Change.UNAVAILABLE }
            .map { if (it.note != null) "${it.capability} (${it.note})" else it.capability }
        val note = if (missing.isEmpty()) "" else " Not enforced: ${missing.joinToString("; ")}."
        return when {
            failed.isNotEmpty() -> "$profile: could not change ${failed.joinToString()}.$note"
            profile == PostureApplier.NORMAL -> "Back to normal: system settings restored."
            else -> "$profile: $enforced system control(s) enforced.$note"
        }
    }

    /** "home: 6 of 6 system controls verified." -- or names what has drifted. */
    fun summarizeAudit(profile: String, items: List<AuditItem>): String {
        if (profile == PostureApplier.NORMAL) return "normal: no posture is active."
        val drifted = items.filter { it.holding == false }.map { it.capability }
        val unknown = items.filter { it.holding == null }.map { it.capability }
        val verified = items.count { it.holding == true }
        val parts = mutableListOf("$profile: $verified of ${items.size} system controls verified.")
        if (drifted.isNotEmpty()) parts += "DRIFTED: ${drifted.joinToString()}."
        if (unknown.isNotEmpty()) parts += "Not enforced: ${unknown.joinToString()}."
        return parts.joinToString(" ")
    }
}
