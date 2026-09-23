package com.forrestlasiter.umbra.net.dns

/**
 * Minimal DNS wire parsing: read the first question (name + type) from a query,
 * and build a "sinkholed" response for a blocked domain. We answer A with
 * 0.0.0.0 (exactly what the Linux /etc/hosts sinkhole does), AAAA with ::, and
 * anything else with NXDOMAIN. Only the question is parsed — no need to walk
 * answer/authority sections or follow compression pointers (a question name is
 * never compressed).
 */
data class DnsQuery(
    val id: Int,
    val flags: Int,
    val qName: String,     // lower-case, no trailing dot, e.g. "graph.facebook.com"
    val qType: Int,
    val raw: ByteArray,
    val questionEnd: Int,  // offset just past qname+qtype+qclass
) {
    companion object {
        const val TYPE_A = 1
        const val TYPE_AAAA = 28
        private const val CLASS_IN = 1
        private const val RCODE_NXDOMAIN = 3
        private const val QUESTION_START = 12

        fun parse(payload: ByteArray): DnsQuery? {
            if (payload.size < 12) return null
            val id = u16(payload, 0)
            val flags = u16(payload, 2)
            val qdcount = u16(payload, 4)
            if (qdcount < 1) return null

            val sb = StringBuilder()
            var i = QUESTION_START
            while (i < payload.size) {
                val len = payload[i].toInt() and 0xFF
                if (len == 0) { i += 1; break }
                if (len and 0xC0 != 0) return null           // compression not expected in a question
                if (i + 1 + len > payload.size) return null
                if (sb.isNotEmpty()) sb.append('.')
                for (j in 0 until len) sb.append((payload[i + 1 + j].toInt() and 0xFF).toChar())
                i += 1 + len
            }
            if (i + 4 > payload.size) return null
            val qType = u16(payload, i)
            i += 4                                            // skip qtype + qclass
            return DnsQuery(id, flags, sb.toString().lowercase(), qType, payload, i)
        }

        private fun u16(b: ByteArray, o: Int) =
            ((b[o].toInt() and 0xFF) shl 8) or (b[o + 1].toInt() and 0xFF)
    }

    /** A response that sinkholes this query (drops it into a black hole). */
    fun buildBlockedResponse(): ByteArray {
        val questionLen = questionEnd - QUESTION_START
        val rdata: ByteArray? = when (qType) {
            TYPE_A -> ByteArray(4)        // 0.0.0.0
            TYPE_AAAA -> ByteArray(16)    // ::
            else -> null                  // -> NXDOMAIN, no answer record
        }
        val hasAnswer = rdata != null
        val ancount = if (hasAnswer) 1 else 0
        val answerLen = if (hasAnswer) 12 + rdata!!.size else 0  // ptr(2)+type(2)+class(2)+ttl(4)+rdlen(2)+rdata

        val out = ByteArray(12 + questionLen + answerLen)
        // Header
        put16(out, 0, id)
        // QR=1, opcode+RD echoed from query, RA=1, rcode
        val rcode = if (hasAnswer) 0 else RCODE_NXDOMAIN
        val rd = flags and 0x0100                              // preserve Recursion Desired
        put16(out, 2, 0x8000 or rd or 0x0080 or rcode)         // QR | RD? | RA | rcode
        put16(out, 4, 1)                                       // qdcount
        put16(out, 6, ancount)                                 // ancount
        put16(out, 8, 0); put16(out, 10, 0)                    // ns/ar count

        // Echo the question verbatim.
        System.arraycopy(raw, QUESTION_START, out, 12, questionLen)

        // Answer (if any), name compressed to the question at offset 12.
        if (hasAnswer) {
            var o = 12 + questionLen
            put16(out, o, 0xC000 or QUESTION_START); o += 2    // name pointer -> 0x000C
            put16(out, o, qType); o += 2
            put16(out, o, CLASS_IN); o += 2
            put16(out, o, 0); put16(out, o + 2, 60); o += 4    // TTL = 60s
            put16(out, o, rdata!!.size); o += 2
            System.arraycopy(rdata, 0, out, o, rdata.size)
        }
        return out
    }

    private fun put16(b: ByteArray, o: Int, v: Int) {
        b[o] = ((v ushr 8) and 0xFF).toByte()
        b[o + 1] = (v and 0xFF).toByte()
    }
}
