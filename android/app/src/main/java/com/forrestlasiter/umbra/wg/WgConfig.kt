package com.forrestlasiter.umbra.wg

/**
 * WireGuard config import — the phone's equivalent of `umbra vpn <file>` on Linux.
 *
 * This is a lightweight VALIDATOR + summary over a wg-quick `.conf`, not the tunnel
 * parser (the wireguard-android library parses the real thing when bringing the
 * tunnel up). It exists so the UI can accept a user-supplied config, confirm it is
 * well-formed, and show what it will connect to — before anything touches the
 * network. Pure Kotlin, unit-tested.
 *
 * You bring your own endpoint (a commercial VPN or a VPS you control) — never a
 * home server, same standalone rule as the Linux build.
 */

class WgConfigError(message: String) : Exception(message)

data class WgConfigSummary(
    val address: String,
    val dns: String?,
    val endpoint: String,
    val allowedIps: String,
    val hasPresharedKey: Boolean,
)

object WgConfig {

    /** Validate a wg-quick config and summarize it, or throw WgConfigError. */
    fun validate(text: String): WgConfigSummary {
        var section = ""
        val iface = HashMap<String, String>()
        val peer = HashMap<String, String>()

        for (rawLine in text.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue
            when {
                line.equals("[Interface]", true) -> section = "interface"
                line.equals("[Peer]", true) -> section = "peer"
                line.startsWith("[") -> section = "other"
                else -> {
                    val k = line.substringBefore('=', "").trim().lowercase()
                    val v = line.substringAfter('=', "").trim()
                    if (k.isEmpty()) continue
                    when (section) {
                        "interface" -> iface[k] = v
                        "peer" -> peer[k] = v
                    }
                }
            }
        }

        val privateKey = iface["privatekey"]
            ?: throw WgConfigError("missing PrivateKey in [Interface]")
        requireKey(privateKey, "PrivateKey")
        val address = iface["address"]
            ?: throw WgConfigError("missing Address in [Interface]")

        val publicKey = peer["publickey"]
            ?: throw WgConfigError("missing PublicKey in [Peer]")
        requireKey(publicKey, "PublicKey")
        val endpoint = peer["endpoint"]
            ?: throw WgConfigError("missing Endpoint in [Peer]")
        requireEndpoint(endpoint)

        peer["presharedkey"]?.let { requireKey(it, "PresharedKey") }

        return WgConfigSummary(
            address = address,
            dns = iface["dns"],
            endpoint = endpoint,
            allowedIps = peer["allowedips"] ?: "0.0.0.0/0, ::/0",
            hasPresharedKey = peer.containsKey("presharedkey"),
        )
    }

    /** A WireGuard key is 32 bytes base64 -> 44 chars ending in '='. */
    private fun requireKey(value: String, name: String) {
        if (value.length != 44 || !value.endsWith("=") ||
            !value.all { it.isLetterOrDigit() || it == '+' || it == '/' || it == '=' }
        ) {
            throw WgConfigError("$name is not a valid WireGuard key")
        }
    }

    private fun requireEndpoint(value: String) {
        val host = value.substringBeforeLast(':', "")
        val port = value.substringAfterLast(':', "").toIntOrNull()
        if (host.isEmpty() || port == null || port !in 1..65535) {
            throw WgConfigError("Endpoint must be host:port")
        }
    }
}
