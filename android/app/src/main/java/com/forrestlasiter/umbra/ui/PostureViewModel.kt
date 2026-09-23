package com.forrestlasiter.umbra.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import com.forrestlasiter.umbra.core.CoreSpec
import com.forrestlasiter.umbra.core.PosturePlan
import com.forrestlasiter.umbra.core.PostureEngine
import com.forrestlasiter.umbra.core.SpecRepository
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
    val wgConfigured: Boolean = false,
    val wgEndpoint: String? = null,
    val message: String? = null,
    val error: String? = null,
)

/**
 * Holds the loaded core spec, the current selection, and the imported WireGuard
 * config state. All posture logic comes from PostureEngine over the spec.
 */
class PostureViewModel(app: Application) : AndroidViewModel(app) {

    private val store = WgConfigStore(app)
    private val _state = MutableStateFlow(PostureUiState())
    val state: StateFlow<PostureUiState> = _state.asStateFlow()

    init { reload() }

    private fun reload() {
        try {
            val spec = SpecRepository(getApplication()).load()
            val names = spec.profiles.keys.filter { it != "normal" }.sorted()
            val selected = names.firstOrNull { it == "travel" } ?: names.firstOrNull() ?: "travel"
            _state.value = PostureUiState(
                spec = spec,
                profileNames = names,
                selected = selected,
                plan = PostureEngine.plan(spec, selected),
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
            plan = PostureEngine.plan(spec, profile),
            message = null,
        )
    }

    fun setActive(active: Boolean) { _state.value = _state.value.copy(active = active) }

    fun setMessage(msg: String?) { _state.value = _state.value.copy(message = msg) }

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
