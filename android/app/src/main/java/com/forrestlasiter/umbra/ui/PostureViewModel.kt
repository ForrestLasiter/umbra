package com.forrestlasiter.umbra.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import com.forrestlasiter.umbra.core.CoreSpec
import com.forrestlasiter.umbra.core.PosturePlan
import com.forrestlasiter.umbra.core.PostureEngine
import com.forrestlasiter.umbra.core.SpecRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class PostureUiState(
    val spec: CoreSpec? = null,
    val profileNames: List<String> = emptyList(),
    val selected: String = "travel",
    val plan: PosturePlan? = null,
    val active: Boolean = false,
    val error: String? = null,
)

/**
 * Holds the loaded core spec and the current selection. All posture logic comes
 * from PostureEngine over the spec — the UI never hardcodes what a profile does.
 */
class PostureViewModel(app: Application) : AndroidViewModel(app) {

    private val _state = MutableStateFlow(PostureUiState())
    val state: StateFlow<PostureUiState> = _state.asStateFlow()

    init { reload() }

    private fun reload() {
        try {
            val spec = SpecRepository(getApplication()).load()
            // Show real postures only (drop "normal", which is the off-state).
            val names = spec.profiles.keys.filter { it != "normal" }.sorted()
            val selected = names.firstOrNull { it == "travel" } ?: names.firstOrNull() ?: "travel"
            _state.value = PostureUiState(
                spec = spec,
                profileNames = names,
                selected = selected,
                plan = PostureEngine.plan(spec, selected),
            )
        } catch (e: Exception) {
            _state.value = _state.value.copy(error = "Could not load core spec: ${e.message}")
        }
    }

    fun select(profile: String) {
        val spec = _state.value.spec ?: return
        _state.value = _state.value.copy(selected = profile, plan = PostureEngine.plan(spec, profile))
    }

    fun setActive(active: Boolean) {
        _state.value = _state.value.copy(active = active)
    }
}
