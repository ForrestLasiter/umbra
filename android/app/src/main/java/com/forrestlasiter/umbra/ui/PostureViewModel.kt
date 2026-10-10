package com.forrestlasiter.umbra.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import com.forrestlasiter.umbra.core.CoreSpec
import com.forrestlasiter.umbra.core.PosturePlan
import com.forrestlasiter.umbra.core.PostureEngine
import com.forrestlasiter.umbra.core.SpecRepository
import com.forrestlasiter.umbra.system.AuditItem
import com.forrestlasiter.umbra.system.PostureApplier
import com.forrestlasiter.umbra.system.SystemMode
import com.forrestlasiter.umbra.system.SystemPosture
import com.forrestlasiter.umbra.wg.WgConfig
import com.forrestlasiter.umbra.wg.WgConfigError
import com.forrestlasiter.umbra.wg.WgConfigStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class PostureUiState(
    val spec: CoreSpec? = null,
    val profileNames: List<String> = emptyList(),
    val selected: String = "travel",
    val plan: PosturePlan? = null,
    val active: Boolean = false,
    // True when Umbra is built into the OS and holds its system permissions.
    val systemBuild: Boolean = false,
    val wgConfigured: Boolean = false,
    val wgEndpoint: String? = null,
    val message: String? = null,
    val error: String? = null,
    // System build: the last measurement of the active posture (null = not measured yet).
    val audit: List<AuditItem>? = null,
    val auditProfile: String? = null,
)

/**
 * Holds the loaded core spec, the current selection, and the imported WireGuard
 * config state. All posture logic comes from PostureEngine over the spec.
 */
class PostureViewModel(app: Application) : AndroidViewModel(app) {

    private val store = WgConfigStore(app)

    // Decided once: which row of the spec's platform matrix this install plans
    // against ("android", or "android_system" when built into the OS).
    private val platform = SystemMode.platform(app)

    // Capabilities this particular OS build cannot deliver (see SystemControl.available).
    private val unavailable = SystemPosture.unavailable(app)
    private val _state = MutableStateFlow(PostureUiState())
    val state: StateFlow<PostureUiState> = _state.asStateFlow()

    init { reload() }

    private fun reload() {
        try {
            val spec = SpecRepository(getApplication()).load()
            val names = spec.profiles.keys.filter { it != "normal" }.sorted()
            // On a system build the tile may already have applied a posture, so
            // open on that one and show it as active.
            val held = SystemPosture.activeProfile(getApplication())
            val selected = names.firstOrNull { it == held }
                ?: names.firstOrNull { it == "travel" } ?: names.firstOrNull() ?: "travel"
            _state.value = PostureUiState(
                spec = spec,
                profileNames = names,
                selected = selected,
                plan = PostureEngine.plan(spec, selected, platform, unavailable),
                active = held != PostureApplier.NORMAL,
                systemBuild = SystemMode.isSystemBuild(getApplication()),
                wgConfigured = store.exists(),
                wgEndpoint = store.summary()?.endpoint,
            )
        } catch (e: Exception) {
            _state.value = _state.value.copy(error = "Could not load core spec: ${e.message}")
        }
    }

    fun select(profile: String) {
        val spec = _state.value.spec ?: return
        _state.value = _state.value.copy(
            selected = profile,
            plan = PostureEngine.plan(spec, profile, platform, unavailable),
            message = null,
        )
    }

    fun setActive(active: Boolean) { _state.value = _state.value.copy(active = active) }

    fun setMessage(msg: String?) { _state.value = _state.value.copy(message = msg) }

    /** Record a measurement of [profile] (or clear it with null). */
    fun setAudit(profile: String?, items: List<AuditItem>?) {
        _state.value = _state.value.copy(audit = items, auditProfile = profile)
    }

    /** Import a WireGuard config the user picked. Sets a user-facing message. */
    fun importWgConfig(text: String) {
        try {
            store.save(text)
            val s = store.summary()
            _state.value = _state.value.copy(
                wgConfigured = true,
                wgEndpoint = s?.endpoint,
                message = "Imported WireGuard config (endpoint ${s?.endpoint}).",
            )
        } catch (e: WgConfigError) {
            _state.value = _state.value.copy(message = "Invalid WireGuard config: ${e.message}")
        } catch (e: Exception) {
            _state.value = _state.value.copy(message = "Could not import config: ${e.message}")
        }
    }
}
