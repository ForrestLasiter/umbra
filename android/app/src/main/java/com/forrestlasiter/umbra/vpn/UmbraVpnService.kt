package com.forrestlasiter.umbra.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log
import com.forrestlasiter.umbra.core.CoreSpec
import com.forrestlasiter.umbra.core.PostureEngine
import com.forrestlasiter.umbra.core.SpecRepository
import com.forrestlasiter.umbra.net.dns.DnsSinkhole
import com.forrestlasiter.umbra.net.dns.TelemetryBlocklist
import java.net.DatagramSocket
import kotlin.concurrent.thread

/**
 * The tunnel that enforces a posture on an unrooted phone. The first datapath
 * implemented is the **DNS telemetry sinkhole** (the `telemetry` capability):
 *
 *   - Routing is DNS-ONLY: only the tunnel's DNS server (10.111.0.1) is routed
 *     through the tun, so every system-resolver lookup reaches us while all other
 *     traffic flows normally over Wi-Fi/cellular — no userspace network stack
 *     needed, no root.
 *   - DnsSinkhole answers blocked telemetry domains locally and forwards the rest
 *     to a real upstream over a protect()ed socket.
 *
 * Capabilities the matrix marks advisory/root-only are NOT touched here; the UI
 * reports them honestly. WireGuard/Tor (which need full capture + a userspace
 * stack) plug in later at the marked seam.
 */
class UmbraVpnService : VpnService() {

    private var tun: ParcelFileDescriptor? = null
    private var sinkhole: DnsSinkhole? = null
    private var worker: Thread? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { teardown(); return START_NOT_STICKY }
        val profile = intent?.getStringExtra(EXTRA_PROFILE) ?: DEFAULT_PROFILE
        startForeground(NOTIF_ID, buildNotification(profile))
        if (tun == null) bringUp(profile)
        return START_STICKY
    }

    private fun bringUp(profileName: String) {
        val spec: CoreSpec = SpecRepository(this).load()
        val plan = PostureEngine.plan(spec, profileName)
        val blocklist = TelemetryBlocklist.forProfile(spec, profileName)

        // DNS-only capture: route just our resolver through the tun. Everything
        // else the device does is untouched (this is a filter, not a full VPN).
        val builder = Builder()
            .setSession("Umbra: $profileName")
            .setMtu(1500)
            .addAddress("10.111.0.2", 32)
            .addDnsServer(TUN_DNS)          // system resolver will target this...
            .addRoute(TUN_DNS, 32)          // ...and only this is pulled into the tun
        runCatching { builder.addDisallowedApplication(packageName) }

        val fd = builder.establish()
        if (fd == null) {
            Log.e(TAG, "establish() returned null (VPN consent not granted?)")
            teardown(); return
        }
        tun = fd

        val sink = DnsSinkhole(fd, blocklist, protect = { s: DatagramSocket -> protect(s) })
        sinkhole = sink
        worker = thread(name = "umbra-dns-sinkhole") { sink.run() }

        Log.i(TAG, "DNS sinkhole up for '$profileName'; " +
            "blocking ${blocklist.size} domains; " +
            "enforceable=${plan.enforceable.map { it.capability }}")
        // TODO(tunnel): when the posture requires wireguard/tor, switch to full
        // capture (addRoute 0.0.0.0/0 + ::/0) and forward through a userspace
        // WireGuard/Tor stack instead of the DNS-only filter above.
    }

    private fun teardown() {
        sinkhole?.stop(); sinkhole = null
        worker?.interrupt(); worker = null
        runCatching { tun?.close() }; tun = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() { teardown(); super.onDestroy() }
    override fun onRevoke() { teardown(); super.onRevoke() }

    private fun buildNotification(profile: String): Notification {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (mgr.getNotificationChannel(CHANNEL) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(CHANNEL, "Umbra posture", NotificationManager.IMPORTANCE_LOW)
            )
        }
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Umbra — $profile")
            .setContentText("Blocking telemetry DNS through the selected posture.")
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "UmbraVpnService"
        private const val CHANNEL = "umbra_posture"
        private const val NOTIF_ID = 1
        private const val TUN_DNS = "10.111.0.1"
        const val DEFAULT_PROFILE = "travel"
        const val EXTRA_PROFILE = "umbra.profile"
        const val ACTION_STOP = "com.forrestlasiter.umbra.STOP"

        fun start(context: Context, profile: String) {
            val i = Intent(context, UmbraVpnService::class.java).putExtra(EXTRA_PROFILE, profile)
            context.startForegroundService(i)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, UmbraVpnService::class.java).setAction(ACTION_STOP))
        }
    }
}
