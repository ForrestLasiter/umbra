package com.forrestlasiter.umbra.system

import android.content.Context

/**
 * Where prior state lives while a posture is active -- the phone's equivalent of
 * the Linux engine's transaction directory.
 *
 * It is an interface so PostureApplier's logic can be tested on a plain JVM with
 * an in-memory map; the real one below is backed by SharedPreferences, which
 * survives the process being killed and the phone rebooting.
 */
interface SnapshotStore {
    fun get(capability: String): String?
    fun put(capability: String, prior: String)
    fun remove(capability: String)

    /** The profile last applied, or null when the phone is at normal. */
    var activeProfile: String?
}

class PrefsSnapshotStore(context: Context) : SnapshotStore {

    private val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    override fun get(capability: String): String? = prefs.getString(PRIOR + capability, null)

    // commit(), not apply(): the snapshot must be on disk BEFORE the control
    // mutates anything. If the process died between an async write and the
    // mutation, the prior state would be lost and the change could not be undone.
    override fun put(capability: String, prior: String) {
        prefs.edit().putString(PRIOR + capability, prior).commit()
    }

    override fun remove(capability: String) {
        prefs.edit().remove(PRIOR + capability).commit()
    }

    override var activeProfile: String?
        get() = prefs.getString(ACTIVE, null)
        set(value) {
            prefs.edit().apply { if (value == null) remove(ACTIVE) else putString(ACTIVE, value) }.commit()
        }

    private companion object {
        const val FILE = "umbra_system_posture"
        const val PRIOR = "prior."
        const val ACTIVE = "active_profile"
    }
}
