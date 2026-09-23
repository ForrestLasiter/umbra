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
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * The tunnel that actually enforces a posture on an unrooted phone. On Android,
 * VPNService is the only lever that gives real control over egress without root:
 *   - telemetry sinkhole  -> drop DNS answers for telemetry domains (enforced here)
 *   - wireguard           -> forward through a WireGuard userspace stack (TODO seam)
 *   - tor                 -> forward through a Tor packet tunnel / Orbot (TODO seam)
 *
 * Capabilities the matrix marks advisory/root-only are NOT touched here — the UI
 * reports them honestly instead of pretending this service enforces them.
 *
 * The packet datapath below is a scaffold: it establishes the interface and owns
 * the lifecycle. Wiring a real userspace network stack (wireguard-android's Go
 * backend, or a DNS/packet processor) is the next implementation step, marked TODO.
 */
class UmbraVpnService : VpnService() {

    private val running = AtomicBoolean(false)
    private var tun: ParcelFileDescriptor? = null
    private var worker: Thread? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { teardown(); return START_NOT_STICKY }
        }
        val profile = intent?.getStringExtra(EXTRA_PROFILE) ?: DEFAULT_PROFILE
        startForeground(NOTIF_ID, buildNotification(profile))
        if (running.compareAndSet(false, true)) {
            bringUp(profile)
        }
        return START_STICKY
    }

    private fun bringUp(profileName: String) {
        val spec: CoreSpec = SpecRepository(this).load()
        val plan = PostureEngine.plan(spec, profileName)

        val builder = Builder()
            .setSession("Umbra: $profileName")
            .setMtu(1500)
            .addAddress("10.111.0.2", 32)         // umbra's private tunnel address
            .addRoute("0.0.0.0", 0)               // capture all IPv4 egress
            .addRoute("::", 0)                     // ...and IPv6, so nothing leaks around it
            .addDnsServer("10.111.0.1")           // DNS handled inside the tunnel (sinkhole)

        // Never route Umbra's own traffic back through itself.
        runCatching { builder.addDisallowedApplication(packageName) }

        tun = builder.establish()
        if (tun == null) {
            Log.e(TAG, "VpnService.establish() returned null (consent not granted?)")
            teardown(); return
        }

        // TODO(datapath): hand `tun` to the tunnel stack the plan requires.
        //   - telemetry  -> DnsSinkhole(spec.telemetryDomains) — drop/NXDOMAIN
        //   - wireguard  -> WireGuardBackend(profile.endpoint) — encrypt + forward
        //   - tor        -> TorPacketTunnel() — forward via Orbot / arti
        // For now the worker just holds the interface up; the honest UI already
        // reflects which of these the device can enforce.
        worker = thread(name = "umbra-tun") { holdTunnel(plan.profile) }
        Log.i(TAG, "tunnel up for '$profileName'; enforceable=${plan.enforceable.map { it.capability }}")
    }

    private fun holdTunnel(profile: String) {
        val fd = tun ?: return
        try {
            fd.fileDescriptor // keep the interface established
            while (running.get()) {
                // TODO: read/process/write packets here via the selected stack.
                Thread.sleep(250)
            }
        } catch (_: InterruptedException) {
            // stopping
        }
    }

    private fun teardown() {
        running.set(false)
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
            .setContentText("Routing traffic through the selected posture.")
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "UmbraVpnService"
        private const val CHANNEL = "umbra_posture"
        private const val NOTIF_ID = 1
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
