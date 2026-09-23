package com.forrestlasiter.umbra.net

/** A parsed UDP datagram sitting inside an IPv4 payload. */
data class UdpDatagram(
    val srcPort: Int,
    val dstPort: Int,
    val payload: ByteArray,   // the UDP data (e.g. a DNS message)
) {
    companion object {
        const val DNS_PORT = 53

        fun parse(ip: Ipv4Packet): UdpDatagram? {
            if (ip.protocol != Ipv4Packet.PROTO_UDP) return null
            val off = ip.payloadOffset
            if (ip.payloadLength < 8) return null
            val buf = ip.raw
            val srcPort = ((buf[off].toInt() and 0xFF) shl 8) or (buf[off + 1].toInt() and 0xFF)
            val dstPort = ((buf[off + 2].toInt() and 0xFF) shl 8) or (buf[off + 3].toInt() and 0xFF)
            val udpLen = ((buf[off + 4].toInt() and 0xFF) shl 8) or (buf[off + 5].toInt() and 0xFF)
            val dataLen = (udpLen - 8).coerceIn(0, ip.length - (off + 8))
            val payload = buf.copyOfRange(off + 8, off + 8 + dataLen)
            return UdpDatagram(srcPort, dstPort, payload)
        }
    }
}
