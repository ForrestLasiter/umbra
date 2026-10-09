package com.forrestlasiter.umbra.system

/** Android's always-on VPN setting, as a pair of variables the tests can inspect. */
internal class FakeAlwaysOn(
    var app: String? = null,
    var lockdown: Boolean = false,
    val events: MutableList<String> = mutableListOf(),
    var readable: Boolean = true,
    var refuseSet: Boolean = false,
) : AlwaysOnVpn {
    var authorized: String? = null

    /** The app whose VPN is established. Tests set it; nothing here starts a VPN. */
    var active: String? = null
    override fun activeApp(): String? = active
    override fun authorize(packageName: String): Boolean { authorized = packageName; return true }
    override fun current(): Pair<String?, Boolean>? = if (readable) app to lockdown else null
    override fun set(packageName: String?, lockdown: Boolean): Boolean {
        if (refuseSet) return false
        events += "always-on=$packageName lockdown=$lockdown"
        app = packageName
        this.lockdown = lockdown
        return true
    }
}

/** A snapshot store that lives in memory. */
internal class MemoryStore : SnapshotStore {
    val map = mutableMapOf<String, String>()
    override fun get(capability: String) = map[capability]
    override fun put(capability: String, prior: String) { map[capability] = prior }
    override fun remove(capability: String) { map.remove(capability) }
    override var activeProfile: String? = null
}

internal const val UMBRA_APP = "com.forrestlasiter.umbra"
internal const val TOR_APP = "org.torproject.android"

/** The one always-on slot, shared by the WireGuard and Tor controls as in the app. */
internal fun vpnSlot(alwaysOn: FakeAlwaysOn, store: SnapshotStore = MemoryStore()) =
    VpnSlot(alwaysOn, store, claimants = setOf(UMBRA_APP, TOR_APP))
