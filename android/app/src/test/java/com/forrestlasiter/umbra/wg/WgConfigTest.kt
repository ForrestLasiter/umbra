package com.forrestlasiter.umbra.wg

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WgConfigTest {

    private val key = "A".repeat(43) + "="        // 44 chars, valid WG-key shape

    private fun config(
        privateKey: String = key,
        address: String = "10.7.0.2/32",
        dns: String? = "1.1.1.1",
        publicKey: String = key,
        endpoint: String = "vpn.example.com:51820",
        psk: String? = null,
    ): String = buildString {
        appendLine("[Interface]")
        appendLine("# an imported profile")
        appendLine("PrivateKey = $privateKey")
        appendLine("Address = $address")
        if (dns != null) appendLine("DNS = $dns")
        appendLine()
        appendLine("[Peer]")
        appendLine("PublicKey = $publicKey")
        if (psk != null) appendLine("PresharedKey = $psk")
        appendLine("Endpoint = $endpoint")
        appendLine("AllowedIPs = 0.0.0.0/0, ::/0")
        appendLine("PersistentKeepalive = 25")
    }

    @Test fun parses_a_valid_config() {
        val s = WgConfig.validate(config())
        assertEquals("vpn.example.com:51820", s.endpoint)
        assertEquals("10.7.0.2/32", s.address)
        assertEquals("1.1.1.1", s.dns)
        assertEquals("0.0.0.0/0, ::/0", s.allowedIps)
        assertFalse(s.hasPresharedKey)
    }

    @Test fun detects_a_preshared_key() {
        assertTrue(WgConfig.validate(config(psk = key)).hasPresharedKey)
    }

    @Test fun dns_is_optional() {
        assertNull(WgConfig.validate(config(dns = null)).dns)
    }

    @Test fun missing_private_key_is_rejected() {
        val text = config().lineSequence().filterNot { it.startsWith("PrivateKey") }.joinToString("\n")
        val e = assertThrows(WgConfigError::class.java) { WgConfig.validate(text) }
        assertTrue(e.message!!.contains("PrivateKey"))
    }

    @Test fun missing_endpoint_is_rejected() {
        val text = config().lineSequence().filterNot { it.startsWith("Endpoint") }.joinToString("\n")
        assertThrows(WgConfigError::class.java) { WgConfig.validate(text) }
    }

    @Test fun a_malformed_key_is_rejected() {
        assertThrows(WgConfigError::class.java) { WgConfig.validate(config(privateKey = "too-short")) }
    }

    @Test fun an_endpoint_without_a_port_is_rejected() {
        assertThrows(WgConfigError::class.java) { WgConfig.validate(config(endpoint = "vpn.example.com")) }
    }
}
