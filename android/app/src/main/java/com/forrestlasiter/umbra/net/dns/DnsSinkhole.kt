package com.forrestlasiter.umbra.net.dns

import android.os.ParcelFileDescriptor
import android.util.Log
import com.forrestlasiter.umbra.net.Ipv4Packet
import com.forrestlasiter.umbra.net.UdpDatagram
import com.forrestlasiter.umbra.vpn.SinkholeStats
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * The datapath that delivers the `telemetry` capability on an unrooted phone.
 *
 * With DNS-only routing, the only packets that reach the tun are the system
 * resolver's DNS queries. For each one:
 *   - blocked domain -> answer 0.0.0.0 / :: locally (a black hole), same as the
 *                       Linux /etc/hosts sinkhole;
 *   - everything else -> forward to a real upstream over a protect()ed socket
 *                        (so the forward bypasses the VPN) and relay the reply.
 *
 * Honest limits (documented): this catches plaintext DNS via the system resolver.
 * Apps that use DoH/DoT or a hardcoded resolver IP bypass it — the same ceiling
 * every no-root DNS filter (and the Linux hosts file) has.
 */
class DnsSinkhole(
    private val tun: ParcelFileDescriptor,
    private val blocklist: TelemetryBlocklist,
    private val protect: (DatagramSocket) -> Boolean,
    private val upstream: InetAddress = InetAddress.getByName(DEFAULT_UPSTREAM),
    private val upstreamPort: Int = 53,
) {
    private val running = AtomicBoolean(false)
    private val input = FileInputStream(tun.fileDescriptor)
    private val output = FileOutputStream(tun.fileDescriptor)
    private val forwarders = Executors.newCachedThreadPool()

    val blockedCount = AtomicLong(0)
    val forwardedCount = AtomicLong(0)

    /** Blocking read loop. Call on a dedicated thread; stop() to end it. */
    fun run() {
        running.set(true)
        val buf = ByteArray(MAX_PACKET)
        Log.i(TAG, "sinkhole up: ${blocklist.size} telemetry domains")
        SinkholeStats.started(blocklist.size)
        while (running.get()) {
            val n = try { input.read(buf) } catch (_: Exception) { break }
            if (n <= 0) continue
            handle(buf.copyOf(n), n)
        }
    }

    private fun handle(packet: ByteArray, n: Int) {
        val ip = Ipv4Packet.parse(packet, n) ?: return
        val udp = UdpDatagram.parse(ip) ?: return
        if (udp.dstPort != UdpDatagram.DNS_PORT) return          // DNS only

        val query = DnsQuery.parse(udp.payload)
        if (query != null && blocklist.isBlocked(query.qName)) {
            writeReply(ip, udp, query.buildBlockedResponse())
            SinkholeStats.update(blockedCount.incrementAndGet(), forwardedCount.get())
        } else {
            forwarders.submit { forward(ip, udp) }               // don't block the reader
        }
    }

    private fun forward(ip: Ipv4Packet, udp: UdpDatagram) {
        try {
            DatagramSocket().use { sock ->
                if (!protect(sock)) return                       // must bypass the VPN
                sock.soTimeout = UPSTREAM_TIMEOUT_MS
                sock.send(DatagramPacket(udp.payload, udp.payload.size, upstream, upstreamPort))
                val rbuf = ByteArray(MAX_PACKET)
                val rp = DatagramPacket(rbuf, rbuf.size)
                sock.receive(rp)
                writeReply(ip, udp, rbuf.copyOf(rp.length))
                SinkholeStats.update(blockedCount.get(), forwardedCount.incrementAndGet())
            }
        } catch (_: Exception) {
            // timeout / io — drop; the client's resolver retries.
        }
    }

    /** Wrap a DNS payload in an IPv4+UDP packet addressed back to the client. */
    private fun writeReply(ip: Ipv4Packet, udp: UdpDatagram, dns: ByteArray) {
        val reply = Ipv4Packet.buildUdp(
            srcAddr = ip.dstAddr, dstAddr = ip.srcAddr,
            srcPort = udp.dstPort, dstPort = udp.srcPort,
            udpPayload = dns,
        )
        synchronized(output) {
            output.write(reply)
            output.flush()
        }
    }

    fun stop() {
        running.set(false)
        forwarders.shutdownNow()
        runCatching { input.close() }
        runCatching { output.close() }
        SinkholeStats.stopped()
    }

    companion object {
        private const val TAG = "DnsSinkhole"
        private const val MAX_PACKET = 32_767
        private const val UPSTREAM_TIMEOUT_MS = 5_000
        const val DEFAULT_UPSTREAM = "1.1.1.1"
    }
}
