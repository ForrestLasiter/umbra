package com.forrestlasiter.umbra.net

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class Ipv4UdpTest {

    private val src = byteArrayOf(10, 111, 0, 1)
    private val dst = byteArrayOf(10, 111, 0, 2)

    @Test fun build_then_parse_round_trips() {
        val payload = "hello-dns".toByteArray()
        val pkt = Ipv4Packet.buildUdp(src, dst, 53, 40000, payload)

        val ip = Ipv4Packet.parse(pkt, pkt.size)!!
        assertEquals(Ipv4Packet.PROTO_UDP, ip.protocol)
        assertArrayEquals(src, ip.srcAddr)
        assertArrayEquals(dst, ip.dstAddr)

        val udp = UdpDatagram.parse(ip)!!
        assertEquals(53, udp.srcPort)
        assertEquals(40000, udp.dstPort)
        assertArrayEquals(payload, udp.payload)
    }

    @Test fun ipv4_header_checksum_is_valid() {
        val pkt = Ipv4Packet.buildUdp(src, dst, 1, 2, ByteArray(4))
        // A correct header checksums to 0 when re-summed including the checksum field.
        assertEquals(0, InternetChecksum.compute(pkt, 0, 20))
    }

    @Test fun total_length_matches_bytes() {
        val payload = ByteArray(20)
        val pkt = Ipv4Packet.buildUdp(src, dst, 1, 2, payload)
        val totalLen = ((pkt[2].toInt() and 0xFF) shl 8) or (pkt[3].toInt() and 0xFF)
        assertEquals(pkt.size, totalLen)
        assertEquals(20 + 8 + 20, pkt.size)
    }

    @Test fun rejects_non_ipv4() {
        val v6 = ByteArray(40); v6[0] = 0x60           // version 6
        assertEquals(null, Ipv4Packet.parse(v6, v6.size))
    }

    @Test fun parses_a_real_udp_datagram_offset() {
        val pkt = Ipv4Packet.buildUdp(src, dst, 5353, 53, "q".toByteArray())
        val ip = Ipv4Packet.parse(pkt, pkt.size)
        assertNotNull(ip)
        assertEquals(20, ip!!.payloadOffset)             // no options -> 20-byte header
    }
}
