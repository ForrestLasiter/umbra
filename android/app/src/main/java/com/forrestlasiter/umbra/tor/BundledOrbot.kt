package com.forrestlasiter.umbra.tor

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.util.Log
import java.io.File

/**
 * An OS that builds Umbra in can also carry Orbot, so Tor works out of the box.
 *
 * Orbot cannot be a preinstalled system app without being modified and
 * re-signed (Android requires system apps to store their native libraries
 * uncompressed; Orbot's release does not). So the OS ships the Tor Project's
 * APK untouched as a plain file, and Umbra installs it once, as an ordinary app:
 * it keeps the Tor Project's signature, updates like any install, and the user
 * can remove it.
 *
 * "Once" is deliberate. If the user uninstalls Orbot, Umbra does not put it
 * back behind their back; the Tor control then reports it as missing.
 */
object BundledOrbot {

    private const val TAG = "UmbraTor"
    private const val PREFS = "umbra_bundled_orbot"
    private const val KEY_ATTEMPTED = "install_attempted"
    private const val ACTION_RESULT = "com.forrestlasiter.umbra.action.ORBOT_INSTALL_RESULT"

    /** Where an OS image may put the APK. Read-only, verified partitions only. */
    private val LOCATIONS = listOf(
        "/product/etc/umbra/tor-provider.apk",
        "/system_ext/etc/umbra/tor-provider.apk",
    )

    fun bundledApk(): File? = LOCATIONS.map(::File).firstOrNull { it.canRead() }

    /**
     * Install the bundled Orbot if the OS carries one, it is not installed, and
     * this has not been tried before. Returns at once; the install finishes in
     * the background. Needs INSTALL_PACKAGES, which only an OS build grants --
     * the caller checks that this is one.
     */
    fun installOnce(context: Context) {
        val app = context.applicationContext
        val apk = bundledApk() ?: return
        if (OrbotHelper.isInstalled(app)) return
        val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_ATTEMPTED, false)) return
        prefs.edit().putBoolean(KEY_ATTEMPTED, true).commit()
        try {
            val installer = app.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            params.setAppPackageName(OrbotHelper.ORBOT_PACKAGE)
            params.setSize(apk.length())
            val id = installer.createSession(params)
            installer.openSession(id).use { session ->
                session.openWrite("orbot", 0, apk.length()).use { out ->
                    apk.inputStream().use { it.copyTo(out) }
                    session.fsync(out)
                }
                val result = PendingIntent.getBroadcast(
                    app, id,
                    Intent(ACTION_RESULT).setClass(app, ResultReceiver::class.java),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
                )
                session.commit(result.intentSender)
            }
            Log.i(TAG, "installing the Orbot this OS ships (${apk.path})")
        } catch (e: Exception) {
            // Let a later boot try again: nothing was installed.
            prefs.edit().remove(KEY_ATTEMPTED).commit()
            Log.w(TAG, "could not start installing the bundled Orbot", e)
        }
    }

    /** Hears how the install went. Not exported: only the system's reply reaches it. */
    class ResultReceiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
            if (status == PackageInstaller.STATUS_SUCCESS) {
                Log.i(TAG, "bundled Orbot installed")
                return
            }
            Log.w(TAG, "bundled Orbot not installed: status $status " +
                intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE))
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().remove(KEY_ATTEMPTED).apply()
        }
    }
}
