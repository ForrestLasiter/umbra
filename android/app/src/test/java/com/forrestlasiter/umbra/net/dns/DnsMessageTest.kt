package com.forrestlasiter.umbra.net.dns

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DnsMessageTest {

    /** Encode a minimal DNS query the way a resolver would put it on the wire. */
    private fun encodeQuery(name: String, type: Int, id: Int = 0x1234): ByteArray {
        val labels = name.split(".")
        val out = ArrayList<Byte>()
        fun put16(v: Int) { out.add(((v ushr 8) and 0xFF).toByte()); out.add((v and 0xFF).toByte()) }
        put16(id); put16(0x0100); put16(1); put16(0); put16(0); put16(0)   // header, RD set
        for (l in labels) { out.add(l.length.toByte()); l.forEach { out.add(it.code.toByte()) } }
        out.add(0)                                                          // root label
        put16(type); put16(1)                                              // qtype, qclass=IN
        return out.toByteArray()
    }

    @Test fun parses_question_name_and_type() {
        val q = DnsQuery.parse(encodeQuery("graph.facebook.com", DnsQuery.TYPE_A))!!
        assertEquals("graph.facebook.com", q.qName)
        assertEquals(DnsQuery.TYPE_A, q.qType)
        assertEquals(0x1234, q.id)
    }

    @Test fun lowercases_the_name() {
        val q = DnsQuery.parse(encodeQuery("Graph.Facebook.COM", DnsQuery.TYPE_A))!!
        assertEquals("graph.facebook.com", q.qName)
    }

    @Test fun blocked_A_response_answers_zero_address() {
        val q = DnsQuery.parse(encodeQuery("app-measurement.com", DnsQuery.TYPE_A))!!
        val r = q.buildBlockedResponse()
        assertEquals(0x1234, ((r[0].toInt() and 0xFF) shl 8) or (r[1].toInt() and 0xFF)) // id echoed
        assertTrue("QR bit set", (r[2].toInt() and 0x80) != 0)
        assertEquals(1, u16(r, 6))                                          // ancount == 1
        // last 4 bytes are the A rdata = 0.0.0.0
        val rdata = r.copyOfRange(r.size - 4, r.size)
        assertTrue(rdata.all { it.toInt() == 0 })
    }

    @Test fun blocked_AAAA_response_answers_zero_v6() {
        val q = DnsQuery.parse(encodeQuery("metrics.mozilla.org", DnsQuery.TYPE_AAAA))!!
        val r = q.buildBlockedResponse()
        assertEquals(1, u16(r, 6))                                          // ancount == 1
        val rdata = r.copyOfRange(r.size - 16, r.size)                      // :: (16 zeros)
        assertTrue(rdata.all { it.toInt() == 0 })
    }

    @Test fun blocked_other_qtype_is_nxdomain() {
        val q = DnsQuery.parse(encodeQuery("analytics.google.com", 15))!!   // MX
        val r = q.buildBlockedResponse()
        assertEquals(0, u16(r, 6))                                          // no answer
        assertEquals(3, r[3].toInt() and 0x0F)                             // rcode NXDOMAIN
    }

    @Test fun rejects_a_truncated_packet() {
        assertNull(DnsQuery.parse(byteArrayOf(0, 1, 2)))
    }

    private fun u16(b: ByteArray, o: Int) = ((b[o].toInt() and 0xFF) shl 8) or (b[o + 1].toInt() and 0xFF)
}
