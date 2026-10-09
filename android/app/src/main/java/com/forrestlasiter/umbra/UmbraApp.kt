package com.forrestlasiter.umbra

import android.app.Application
import com.forrestlasiter.umbra.system.SystemMode
import com.forrestlasiter.umbra.system.SystemPosture
import com.forrestlasiter.umbra.vpn.Tunnels

/**
 * Runs once whenever Android starts this app's process, before any screen,
 * service or receiver.
 *
 * It exists for one case: on an OS build, Umbra can be the phone's always-on VPN.
 * After a reboot the OS starts our VPN service by itself, with nobody having
 * opened the app. The settings a posture changed survived the reboot; the tunnel
 * did not. So here we say what "the OS woke the VPN" should mean -- re-assert the
 * posture the phone is in -- and make sure the tunnel backend exists to hear it.
 */
class UmbraApp : Application() {

    override fun onCreate() {
        super.onCreate()
        Tunnels.onAlwaysOn = { SystemPosture.reassertInBackground(this) }
        if (Tunnels.bundled && SystemMode.isSystemBuild(this)) {
            Tunnels.prepare(this)       // creates the backend, which registers the hook
        }
    }
}
