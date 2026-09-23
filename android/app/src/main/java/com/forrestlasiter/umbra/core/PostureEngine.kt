package com.forrestlasiter.umbra.core

/**
 * The Android adapter's brain: given the profile the user picked, decide — per
 * required capability — what this device will ACTUALLY do, and say so honestly.
 *
 * This is the phone's answer to the project's core promise: never render a
 * capability as "on" when the platform can't enforce it. Each item carries the
 * enforcement level from the core matrix plus a concrete, user-facing plan.
 */

/** What the app will do about one capability on this device. */
enum class PlannedAction {
    ENFORCE,          // the VPN/app does it now
    REQUEST_CONSENT,  // one-time OS grant needed (VPN consent / entitlement), then enforced
    NEEDS_TUNNEL,     // enforced only while the Umbra tunnel is running
    NEEDS_ROOT,       // impossible without root / custom OS
    GUIDE_TO_SETTING, // advisory: deep-link the user to the OS toggle, claim nothing
    UNAVAILABLE,      // not possible on this platform
}

data class PostureItem(
    val capability: String,
    val summary: String,
    val enforcement: Enforcement,
    val reason: String,
    val action: PlannedAction,
) {
    val honestlyOn: Boolean get() = action == PlannedAction.ENFORCE
}

data class PosturePlan(
    val profile: String,
    val items: List<PostureItem>,
) {
    /** Capabilities the app can enforce right now (drives the VPN config). */
    val enforceable: List<PostureItem> get() = items.filter { it.action == PlannedAction.ENFORCE || it.action == PlannedAction.NEEDS_TUNNEL || it.action == PlannedAction.REQUEST_CONSENT }
    val advisory: List<PostureItem> get() = items.filter { it.action == PlannedAction.GUIDE_TO_SETTING }
}

object PostureEngine {

    fun plan(spec: CoreSpec, profileName: String): PosturePlan {
        val profile = spec.profiles[profileName]
            ?: return PosturePlan(profileName, emptyList())
        val items = profile.requires.map { cap ->
            val support = spec.support(cap)
            val level = support.enforcement
            PostureItem(
                capability = cap,
                summary = spec.capabilities[cap]?.description ?: cap,
                enforcement = level,
                reason = support.reason,
                action = actionFor(level),
            )
        }
        return PosturePlan(profileName, items)
    }

    private fun actionFor(level: Enforcement): PlannedAction = when (level) {
        Enforcement.ENFORCED -> PlannedAction.ENFORCE
        Enforcement.REQUIRES_ENTITLEMENT -> PlannedAction.REQUEST_CONSENT
        Enforcement.REQUIRES_VPN_PROFILE -> PlannedAction.NEEDS_TUNNEL
        Enforcement.REQUIRES_ROOTED_OS -> PlannedAction.NEEDS_ROOT
        Enforcement.ADVISORY -> PlannedAction.GUIDE_TO_SETTING
        Enforcement.UNAVAILABLE -> PlannedAction.UNAVAILABLE
    }
}
