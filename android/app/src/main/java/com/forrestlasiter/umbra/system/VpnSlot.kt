package com.forrestlasiter.umbra.system

/*
 * Android has ONE always-on VPN setting per user, and two of Umbra's controls
 * want it: WireGuard pins Umbra itself, Tor pins the Tor provider app. If each
 * kept its own "what was there before" they would corrupt each other on a switch
 * between two tunnel profiles: the second would record the FIRST control's pin
 * as the user's original, and leaving the posture would restore a killswitch
 * with no tunnel behind it.
 *
 * So the slot has one ledger, shared by both controls:
 *
 *   claim()    record what the slot held before Umbra touched it (first claim only)
 *   pin(app)   hand the slot to `app`, with lockdown
 *   release()  give the slot back -- unless the other control now holds it, in
 *              which case the slot (and the debt to the user) has moved to it
 *
 * Handing over with a single pin() is also what keeps a switch between two
 * tunnel profiles fail-closed: lockdown moves from one app to the other without
 * ever being off in between.
 */
class VpnSlot(
    private val alwaysOn: AlwaysOnVpn,
    private val store: SnapshotStore,
    /** Every app an Umbra control may pin. A slot held by one of these is "ours". */
    private val claimants: Set<String>,
) {

    /** The current always-on app (or null) and whether lockdown is on. Null if unreadable. */
    fun current(): Pair<String?, Boolean>? = alwaysOn.current()

    /** True when [packageName] is the always-on app and lockdown is on. Null if unreadable. */
    fun pinnedTo(packageName: String): Boolean? {
        val (app, lockdown) = alwaysOn.current() ?: return null
        return lockdown && app == packageName
    }

    /**
     * Remember the user's own setting before anything is changed. Safe to call
     * every time: only the first claim records, so a hand-over from the other
     * control keeps the ORIGINAL, not that control's pin.
     */
    fun claim(): Boolean {
        if (store.get(KEY) != null) return true
        val (app, lockdown) = alwaysOn.current() ?: return false
        store.put(KEY, "${app.orEmpty()}|$lockdown")
        return true
    }

    /** Make [packageName] the always-on VPN with lockdown, with no consent dialog. */
    fun pin(packageName: String): Boolean =
        alwaysOn.authorize(packageName) && alwaysOn.set(packageName, lockdown = true)

    /**
     * [packageName]'s control is done with the slot.
     *
     *  - Still ours: put the user's original setting back and forget it.
     *  - Now held by the other control: leave everything; it will release later.
     *  - Changed by someone outside Umbra: it is theirs now. Forget our record
     *    rather than overwrite a choice the user made after us.
     */
    fun release(packageName: String): Boolean {
        val (app, _) = alwaysOn.current() ?: return false
        if (app != packageName && app in claimants) return true
        val original = store.get(KEY) ?: return true
        if (app == packageName) {
            val parts = original.split('|')
            if (parts.size != 2) return false
            val priorApp = parts[0].ifEmpty { null }
            val priorLockdown = parts[1].toBoolean()
            // If it was already pinned to this app before Umbra's posture, leave it.
            val alreadyTheirs = priorApp == packageName && priorLockdown
            if (!alreadyTheirs && !alwaysOn.set(priorApp, priorLockdown)) return false
        }
        store.remove(KEY)
        return true
    }

    companion object {
        /** The ledger's key in the snapshot store. Not a capability name. */
        const val KEY = "vpn_slot"
    }
}
