package com.forrestlasiter.umbra.tor

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * Tor on an unrooted phone is provided by **Orbot** (the Guardian Project's Tor
 * app). Umbra detects it, sends the user to install it if missing, and requests
 * it to start; Orbot's own VPN mode carries all traffic over Tor. Umbra
 * orchestrates — it does not re-implement Tor.
 *
 * (A self-contained path — our tun forwarding to Orbot's SOCKS 127.0.0.1:9050 via
 * tun2socks — is a future option; today we lean on Orbot's VPN mode, which is the
 * honest no-root way to route everything.)
 */
object OrbotHelper {

    const val ORBOT_PACKAGE = "org.torproject.android"
    const val SOCKS_HOST = "127.0.0.1"
    const val SOCKS_PORT = 9050
    const val HTTP_PORT = 8118

    // Orbot's public control intents.
    private const val ACTION_START = "org.torproject.android.intent.action.START"
    private const val EXTRA_PACKAGE_NAME = "org.torproject.android.intent.extra.PACKAGE_NAME"

    fun isInstalled(context: Context): Boolean = try {
        context.packageManager.getPackageInfo(ORBOT_PACKAGE, 0)
        true
    } catch (_: Exception) {
        false
    }

    /** Ask Orbot to start (the user still confirms Orbot's own VPN consent). */
    fun requestStart(context: Context) {
        val intent = Intent(ACTION_START).apply {
            setPackage(ORBOT_PACKAGE)
            putExtra(EXTRA_PACKAGE_NAME, context.packageName)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        runCatching { context.startActivity(intent) }
            .onFailure { runCatching { context.sendBroadcast(intent) } }
    }

    /** Where to get Orbot when it isn't installed (Play, F-Droid fallback). */
    fun installIntent(): Intent =
        Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$ORBOT_PACKAGE"))

    fun installFallbackIntent(): Intent =
        Intent(Intent.ACTION_VIEW, Uri.parse("https://f-droid.org/packages/$ORBOT_PACKAGE/"))
}
