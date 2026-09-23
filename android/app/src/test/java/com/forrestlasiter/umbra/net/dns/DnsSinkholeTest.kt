package com.forrestlasiter.umbra.net.dns

import com.forrestlasiter.umbra.net.Ipv4Packet
import com.forrestlasiter.umbra.net.UdpDatagram
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * End-to-end test of the sinkhole's pure decision: a real DNS query packet in,
 * a complete IPv4/UDP reply (or null) out. Exercises every layer at once.
 */
class DnsSinkholeTest {

    private val client = byteArrayOf(10, 111, 0, 2)
    private val resolver = byteArrayOf(10, 111, 0, 1)
    private val list = TelemetryBlocklist(setOf("graph.facebook.com"))

    private fun encodeQuery(name: String, type: Int): ByteArray {
        val out = ArrayList<Byte>()
        fun p16(v: Int) { out.add(((v ushr 8) and 0xFF).toByte()); out.add((v and 0xFF).toByte()) }
        p16(0x1234); p16(0x0100); p16(1); p16(0); p16(0); p16(0)
        name.split(".").forEach { l -> out.add(l.length.toByte()); l.forEach { out.add(it.code.toByte()) } }
        out.add(0); p16(type); p16(1)
        return out.toByteArray()
    }

    private fun queryPacket(name: String, type: Int = DnsQuery.TYPE_A): ByteArray =
        Ipv4Packet.buildUdp(client, resolver, 33333, 53, encodeQuery(name, type))

    @Test fun blocked_query_yields_a_reply_addressed_back_to_the_client() {
        val pkt = queryPacket("graph.facebook.com")
        val reply = DnsSinkhole.sinkholeReply(pkt, pkt.size, list)!!

        val ip = Ipv4Packet.parse(reply, reply.size)!!
        assertArrayEquals(resolver, ip.srcAddr)          // answered "from" the resolver
        assertArrayEquals(client, ip.dstAddr)            // ...to the asking client

        val udp = UdpDatagram.parse(ip)!!
        assertEquals(53, udp.srcPort)
        assertEquals(33333, udp.dstPort)

        val d = udp.payload
        assertEquals(1, ((d[6].toInt() and 0xFF) shl 8) or (d[7].toInt() and 0xFF)) // ancount
        assertArrayEquals(byteArrayOf(0, 0, 0, 0), d.copyOfRange(d.size - 4, d.size)) // 0.0.0.0
    }

    @Test fun subdomain_of_a_blocked_domain_is_sinkholed() {
        val pkt = queryPacket("edge.graph.facebook.com")
        assertEquals(true, DnsSinkhole.sinkholeReply(pkt, pkt.size, list) != null)
    }

    @Test fun unblocked_query_is_forwarded_not_sinkholed() {
        val pkt = queryPacket("example.com")
        assertNull(DnsSinkhole.sinkholeReply(pkt, pkt.size, list))
    }

    @Test fun non_dns_udp_is_ignored() {
        val pkt = Ipv4Packet.buildUdp(client, resolver, 33333, 443, byteArrayOf(1, 2, 3))
        assertNull(DnsSinkhole.sinkholeReply(pkt, pkt.size, list))
    }
}
