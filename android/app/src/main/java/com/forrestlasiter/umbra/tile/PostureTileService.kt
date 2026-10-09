package com.forrestlasiter.umbra.tile

import android.app.AlertDialog
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.forrestlasiter.umbra.R
import com.forrestlasiter.umbra.core.SpecRepository
import com.forrestlasiter.umbra.system.PostureApplier
import com.forrestlasiter.umbra.system.SystemMode
import com.forrestlasiter.umbra.system.SystemPosture
import com.forrestlasiter.umbra.ui.MainActivity

/**
 * The Quick Settings tile: the phone's version of the Linux tray toggle.
 *
 * On a system build, tapping it lists the profiles and applies the one you pick
 * with the system controls. It asks rather than cycling, because cycling would
 * walk you through `paranoid` on the way back to `normal`.
 *
 * On a normal install there are no system controls, and tunnel postures need the
 * VPN-consent screen, so the tile simply opens the app.
 *
 * The tile shows the posture the system controls are holding -- never a posture
 * that was requested but failed to apply.
 */
class PostureTileService : TileService() {

    override fun onStartListening() = refresh()

    override fun onClick() {
        if (!SystemMode.isSystemBuild(this)) {
            openApp()
            return
        }
        // Don't let a posture be dropped from the lock screen.
        if (isLocked) unlockAndRun { chooseProfile() } else chooseProfile()
    }

    private fun chooseProfile() {
        val spec = try { SpecRepository(this).load() } catch (e: Exception) { openApp(); return }
        // normal first (the way out), then the postures in a stable order.
        val profiles = listOf(PostureApplier.NORMAL) +
            spec.profiles.keys.filter { it != PostureApplier.NORMAL }.sorted()
        val active = SystemPosture.activeProfile(this)
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.tile_choose_posture)
            .setSingleChoiceItems(profiles.toTypedArray(), profiles.indexOf(active)) { d, which ->
                // Off the main thread; the tile is redrawn when it has finished,
                // so it shows the posture that was actually reached.
                SystemPosture.applyInBackground(this, profiles[which]) { refresh() }
                d.dismiss()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .create()
        showDialog(dialog)
    }

    private fun refresh() {
        val tile = qsTile ?: return
        val active = SystemPosture.activeProfile(this)
        tile.label = getString(R.string.tile_label)
        tile.state = if (active == PostureApplier.NORMAL) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) tile.subtitle = active
        // Screen readers get the posture too, not just the word "Umbra".
        tile.contentDescription = getString(R.string.tile_content_description, active)
        tile.updateTile()
    }

    @Suppress("DEPRECATION", "StartActivityAndCollapseDeprecated")
    private fun openApp() {
        val intent = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(
                PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE)
            )
        } else {
            startActivityAndCollapse(intent)
        }
    }
}
