package com.forrestlasiter.umbra.wg

import android.content.Context
import java.io.File

/**
 * Stores the imported WireGuard config in app-private storage — the phone's
 * `/etc/wireguard/vpn.conf`. Only this app can read it (Android's per-app
 * sandbox); it never leaves the device.
 */
class WgConfigStore(context: Context) {

    private val dir = File(context.filesDir, "wireguard").apply { mkdirs() }
    private val file = File(dir, "$NAME.conf")

    fun save(text: String) {
        WgConfig.validate(text)              // never store a config we couldn't parse
        file.writeText(text)
    }

    fun load(): String? = if (file.exists()) file.readText() else null

    fun summary(): WgConfigSummary? = load()?.let { runCatching { WgConfig.validate(it) }.getOrNull() }

    fun exists(): Boolean = file.exists()

    fun clear() { file.delete() }

    companion object {
        const val NAME = "vpn"               // matches the Linux `umbra vpn --name vpn`
    }
}
