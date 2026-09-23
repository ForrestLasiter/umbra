package com.forrestlasiter.umbra.core

import android.content.Context

/**
 * Loads the bundled core spec (assets/umbra-core.json). The asset is a verbatim
 * copy of the repo's spec/umbra-core.json; run scripts/sync-spec.sh after
 * `umbra export-spec` to refresh it so the app can never drift from the core.
 */
class SpecRepository(private val context: Context) {

    fun load(): CoreSpec {
        val text = context.assets.open(ASSET_NAME).bufferedReader().use { it.readText() }
        return CoreSpec.parse(text)
    }

    companion object {
        const val ASSET_NAME = "umbra-core.json"
    }
}
