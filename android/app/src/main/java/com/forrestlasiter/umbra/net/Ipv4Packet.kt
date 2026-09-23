package com.forrestlasiter.umbra.net

/**
 * Just enough IPv4 to route DNS through the sinkhole: parse the header to find
 * UDP datagrams, and rebuild a reply packet (src/dst swapped) with a correct
 * header checksum. Not a general IP stack — the DNS-only route means only DNS
 * packets ever reach us.
 */
data class Ipv4Packet(
    val raw: ByteArray,
    val length: Int,
    val ihl: Int,             // header length in bytes
    val protocol: Int,        // 17 = UDP
    val srcAddr: ByteArray,   // 4 bytes
    val dstAddr: ByteArray,   // 4 bytes
) {
    val payloadOffset: Int get() = ihl
    val payloadLength: Int get() = length - ihl

    companion object {
        const val PROTO_UDP = 17

        fun parse(buf: ByteArray, length: Int): Ipv4Packet? {
            if (length < 20) return null
            val version = (buf[0].toInt() and 0xF0) ushr 4
            if (version != 4) return null
            val ihl = (buf[0].toInt() and 0x0F) * 4
            if (ihl < 20 || ihl > length) return null
            val protocol = buf[9].toInt() and 0xFF
            val src = buf.copyOfRange(12, 16)
            val dst = buf.copyOfRange(16, 20)
            return Ipv4Packet(buf, length, ihl, protocol, src, dst)
        }

        /**
         * Assemble a complete IPv4 + UDP packet. Recomputes the IPv4 header
         * checksum and the UDP checksum (pseudo-header included).
         */
        fun buildUdp(
            srcAddr: ByteArray, dstAddr: ByteArray,
            srcPort: Int, dstPort: Int, udpPayload: ByteArray,
        ): ByteArray {
            val udpLen = 8 + udpPayload.size
            val totalLen = 20 + udpLen
            val p = ByteArray(totalLen)

            // --- IPv4 header (20 bytes, no options) ---
            p[0] = 0x45.toByte()                       // version 4, IHL 5
            p[1] = 0                                    // DSCP/ECN
            p[2] = ((totalLen ushr 8) and 0xFF).toByte()
            p[3] = (totalLen and 0xFF).toByte()
            // id 0, flags 0, frag 0 (bytes 4..7 left zero)
            p[8] = 64                                   // TTL
            p[9] = PROTO_UDP.toByte()
            // header checksum bytes 10..11 left zero for the computation
            System.arraycopy(srcAddr, 0, p, 12, 4)
            System.arraycopy(dstAddr, 0, p, 16, 4)
            val ipChk = InternetChecksum.compute(p, 0, 20)
            p[10] = ((ipChk ushr 8) and 0xFF).toByte()
            p[11] = (ipChk and 0xFF).toByte()

            // --- UDP header (8 bytes) + payload ---
            val u = 20
            p[u] = ((srcPort ushr 8) and 0xFF).toByte()
            p[u + 1] = (srcPort and 0xFF).toByte()
            p[u + 2] = ((dstPort ushr 8) and 0xFF).toByte()
            p[u + 3] = (dstPort and 0xFF).toByte()
            p[u + 4] = ((udpLen ushr 8) and 0xFF).toByte()
            p[u + 5] = (udpLen and 0xFF).toByte()
            // checksum bytes 6..7 left zero, then filled below
            System.arraycopy(udpPayload, 0, p, u + 8, udpPayload.size)

            // UDP checksum over pseudo-header (src, dst, zero, proto, udpLen) + UDP.
            var seed = InternetChecksum.partialSum(srcAddr, 0, 4) +
                InternetChecksum.partialSum(dstAddr, 0, 4) +
                PROTO_UDP.toLong() + udpLen.toLong()
            var udpChk = InternetChecksum.compute(p, u, udpLen, seed)
            if (udpChk == 0) udpChk = 0xFFFF          // 0 means "no checksum"; use all-ones
            p[u + 6] = ((udpChk ushr 8) and 0xFF).toByte()
            p[u + 7] = (udpChk and 0xFF).toByte()
            return p
        }
    }
}
