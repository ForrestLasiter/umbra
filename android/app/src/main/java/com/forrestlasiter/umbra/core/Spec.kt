package com.forrestlasiter.umbra.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * The platform-agnostic Umbra core, as shipped in `spec/umbra-core.json` (emitted
 * by the Python reference via `umbra export-spec`). Android does not re-derive the
 * posture model — it consumes exactly this, so the phone and the laptop agree on
 * what every profile means and what this platform can honestly enforce.
 *
 * Keep these types in step with umbra/spec.py::build_spec().
 */

/** The six honest promise levels. Mirrors umbra.platform.Enforcement. */
enum class Enforcement(val wire: String) {
    ENFORCED("enforced"),
    REQUIRES_ENTITLEMENT("requires_entitlement"),
    REQUIRES_VPN_PROFILE("requires_vpn_profile"),
    REQUIRES_ROOTED_OS("requires_rooted_os"),
    ADVISORY("advisory"),
    UNAVAILABLE("unavailable");

    /** True when the app can actually change the state (vs. only observe/report). */
    val actionable: Boolean
        get() = this == ENFORCED || this == REQUIRES_ENTITLEMENT ||
            this == REQUIRES_VPN_PROFILE || this == REQUIRES_ROOTED_OS

    companion object {
        fun fromWire(s: String): Enforcement =
            entries.firstOrNull { it.wire == s } ?: UNAVAILABLE
    }
}

@Serializable
data class EnforcementLevel(val name: String, val description: String)

@Serializable
data class Capability(
    val description: String,
    val controls: List<String> = emptyList(),
)

@Serializable
data class PlatformCapability(
    val level: String,
    val reason: String,
) {
    val enforcement: Enforcement get() = Enforcement.fromWire(level)
}

@Serializable
data class PlatformSpec(
    val description: String,
    val capabilities: Map<String, PlatformCapability> = emptyMap(),
)

@Serializable
data class ProfileSpec(
    val description: String = "",
    @SerialName("fail_mode") val failMode: String = "closed",
    val requires: List<String> = emptyList(),
    @SerialName("telemetry_blocklists") val telemetryBlocklists: List<String> = emptyList(),
)

@Serializable
data class CoreSpec(
    @SerialName("umbra_spec_version") val specVersion: String,
    @SerialName("engine_version") val engineVersion: String,
    @SerialName("enforcement_levels") val enforcementLevels: List<EnforcementLevel> = emptyList(),
    val capabilities: Map<String, Capability> = emptyMap(),
    val platforms: Map<String, PlatformSpec> = emptyMap(),
    @SerialName("telemetry_blocklists") val telemetryBlocklists: Map<String, List<String>> = emptyMap(),
    val profiles: Map<String, ProfileSpec> = emptyMap(),
) {
    /** The enforcement level THIS platform (android) can promise for a capability. */
    fun support(capability: String, platform: String = "android"): PlatformCapability =
        platforms[platform]?.capabilities?.get(capability)
            ?: PlatformCapability("unavailable", "capability not in spec")

    /** The de-duplicated union of telemetry domains a profile sinkholes. */
    fun telemetryDomains(profileName: String): Set<String> {
        val lists = profiles[profileName]?.telemetryBlocklists ?: emptyList()
        return lists.flatMap { telemetryBlocklists[it] ?: emptyList() }.toSet()
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): CoreSpec = json.decodeFromString(text)
    }
}
