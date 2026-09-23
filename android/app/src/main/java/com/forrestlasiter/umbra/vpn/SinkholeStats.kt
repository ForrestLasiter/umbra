package com.forrestlasiter.umbra.vpn

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Process-wide live stats for the DNS sinkhole, so the UI can show what the
 * tunnel is actually doing (blocked vs forwarded) without binding to the service.
 * The service and the Activity run in the same process, so a shared StateFlow is
 * enough.
 */
object SinkholeStats {

    data class Snapshot(
        val active: Boolean = false,
        val domains: Int = 0,
        val blocked: Long = 0,
        val forwarded: Long = 0,
    )

    private val _flow = MutableStateFlow(Snapshot())
    val flow: StateFlow<Snapshot> = _flow.asStateFlow()

    fun started(domains: Int) { _flow.value = Snapshot(active = true, domains = domains) }

    fun update(blocked: Long, forwarded: Long) {
        _flow.value = _flow.value.copy(blocked = blocked, forwarded = forwarded)
    }

    fun stopped() { _flow.value = _flow.value.copy(active = false) }
}
