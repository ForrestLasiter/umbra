package com.forrestlasiter.umbra.ui

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.forrestlasiter.umbra.core.Enforcement
import com.forrestlasiter.umbra.core.PlannedAction
import com.forrestlasiter.umbra.core.PostureItem
import com.forrestlasiter.umbra.system.AuditItem
import com.forrestlasiter.umbra.system.PostureApplier
import com.forrestlasiter.umbra.system.PostureReport
import com.forrestlasiter.umbra.system.SystemPosture
import com.forrestlasiter.umbra.tor.OrbotHelper
import com.forrestlasiter.umbra.vpn.SinkholeStats
import com.forrestlasiter.umbra.vpn.TunnelController
import com.forrestlasiter.umbra.vpn.TunnelMode

class MainActivity : ComponentActivity() {

    private val vm: PostureViewModel by viewModels()
    private val tunnels by lazy { TunnelController(applicationContext) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface(modifier = Modifier.fillMaxSize()) { PostureScreen(vm) }
            }
        }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun PostureScreen(vm: PostureViewModel) {
        val state by vm.state.collectAsStateWithLifecycle()

        // Pick a WireGuard .conf and import it.
        val pickConfig = rememberLauncherForActivityResult(
            ActivityResultContracts.OpenDocument()
        ) { uri ->
            if (uri != null) {
                val text = runCatching {
                    contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
                }.getOrNull()
                if (text != null) vm.importWgConfig(text)
                else vm.setMessage("Could not read the selected file.")
            }
        }

        // VPN consent: one grant covers both the sinkhole and the WireGuard tunnel.
        val consent = rememberLauncherForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            if (result.resultCode == Activity.RESULT_OK) startEnforcement(state)
            else vm.setMessage("VPN permission is required to enforce this posture.")
        }

        fun activate() {
            // An OS build authorizes its own tunnel, so there is no dialog to show.
            val prepare: Intent? = if (state.systemBuild) null else VpnService.prepare(this)
            if (prepare != null) consent.launch(prepare) else startEnforcement(state)
        }

        fun deactivate() = stopEnforcement(state)

        Column(
            Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("Umbra", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text(
                "Pick a posture. This device enforces what it honestly can and tells " +
                    "you the rest — it does not pretend to be the Linux build.",
                style = MaterialTheme.typography.bodySmall
            )

            state.error?.let {
                Card { Text(it, Modifier.padding(12.dp), color = MaterialTheme.colorScheme.error) }
                return@Column
            }

            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                state.profileNames.forEachIndexed { i, name ->
                    SegmentedButton(
                        selected = name == state.selected,
                        onClick = { vm.select(name) },
                        shape = SegmentedButtonDefaults.itemShape(i, state.profileNames.size),
                    ) { Text(name) }
                }
            }

            // Tor postures (paranoid) route through Orbot. Show it first — it
            // takes precedence over WireGuard for "go dark".
            val needsTor = state.plan?.items?.any {
                it.capability == "tor" && it.action == PlannedAction.NEEDS_TUNNEL
            } == true
            if (needsTor) OrbotCard()

            // WireGuard config: needed by tunnel postures without Tor. BYO endpoint.
            val needsWg = !needsTor && state.plan?.items?.any {
                it.capability == "wireguard" && it.action == PlannedAction.REQUEST_CONSENT
            } == true
            if (needsWg) WgConfigCard(state, onImport = {
                pickConfig.launch(arrayOf("*/*"))       // .conf has no registered MIME type
            })

            Button(
                onClick = { if (state.active) deactivate() else activate() },
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (state.active) "Deactivate" else "Go dark: ${state.selected}") }

            state.message?.let {
                Card { Text(it, Modifier.padding(12.dp), style = MaterialTheme.typography.bodySmall) }
            }

            // Live DNS-sinkhole counters (telemetry postures).
            val stats by SinkholeStats.flow.collectAsStateWithLifecycle()
            if (stats.active) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("DNS sinkhole", fontWeight = FontWeight.SemiBold)
                        Text("${stats.blocked} blocked · ${stats.forwarded} forwarded · " +
                            "${stats.domains} domains",
                            style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            // OS build: what was applied can drift, so show a fresh measurement.
            if (state.systemBuild && state.active) {
                LaunchedEffect(Unit) { if (state.audit == null) measure() }
                AuditCard(state.auditProfile, state.audit, onCheck = { measure() })
            }

            HorizontalDivider()
            Text("What ${state.selected} means on this device",
                style = MaterialTheme.typography.titleMedium)
            state.plan?.items?.forEach { CapabilityRow(it) }
        }
    }

    /**
     * Everything here runs on the posture thread, not the main thread: system
     * controls wait for the OS to confirm, and the WireGuard library deadlocks if
     * the main thread is the one waiting for its service to start. The view
     * model's setters are safe to call from any thread.
     */
    private fun startEnforcement(state: PostureUiState) {
        val plan = state.plan ?: return
        val profile = state.selected
        vm.setMessage("Applying $profile…")
        SystemPosture.inBackground {
            // System controls first (they need no consent and cannot half-start),
            // then the tunnel. On a normal install `system` is null and only the
            // tunnel runs, exactly as before.
            val system = SystemPosture.apply(this, profile)
            val systemNote = system?.let { SystemPosture.summarize(profile, it) }
            // On an OS build a posture may need no tunnel at all (every capability
            // is a system control). That is success, not "nothing to enforce".
            if (system != null && tunnels.modeFor(plan) == TunnelMode.NONE) {
                vm.setActive(true)
                vm.setMessage(systemNote)
                vm.setAudit(SystemPosture.activeProfile(this), SystemPosture.audit(this))
                return@inBackground
            }
            val error = tunnels.activate(profile, plan)
            when {
                error == null -> { vm.setActive(true); vm.setMessage(systemNote ?: "Enforcing $profile.") }
                // The tunnel failed but system controls are holding: say both, and
                // stay "active" so Deactivate is offered and restores them.
                system != null -> { vm.setActive(true); vm.setMessage("$systemNote Tunnel: $error") }
                else -> vm.setMessage(error)
            }
        }
    }

    private fun stopEnforcement(state: PostureUiState) {
        SystemPosture.inBackground {
            state.plan?.let { tunnels.deactivate(it) }
            // System build: put back every setting the posture changed. A no-op
            // (returns null) on a normal install.
            val restored = SystemPosture.apply(this, PostureApplier.NORMAL)
            vm.setActive(false)
            vm.setAudit(null, null)
            if (restored != null) vm.setMessage(SystemPosture.summarize(PostureApplier.NORMAL, restored))
        }
    }

    /** Measure the active posture on the posture thread and show the result. */
    private fun measure() {
        SystemPosture.inBackground {
            vm.setAudit(SystemPosture.activeProfile(this), SystemPosture.audit(this))
        }
    }

    /**
     * "Is it holding?" -- one line per control the active profile enforces here,
     * from a measurement taken now, not from what was applied earlier. Each state
     * is spelled out in words, so it does not depend on telling colours apart.
     */
    @Composable
    private fun AuditCard(profile: String?, items: List<AuditItem>?, onCheck: () -> Unit) {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Is it holding?", fontWeight = FontWeight.SemiBold)
                if (items == null || profile == null) {
                    Text("Measuring…", style = MaterialTheme.typography.bodySmall)
                } else {
                    Text(PostureReport.summarizeAudit(profile, items),
                        style = MaterialTheme.typography.bodySmall)
                    items.forEach { item ->
                        val (label, color) = when (item.holding) {
                            true -> "holding" to MaterialTheme.colorScheme.primary
                            false -> "DRIFTED" to MaterialTheme.colorScheme.error
                            null -> "not enforced" to MaterialTheme.colorScheme.tertiary
                        }
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(item.capability, style = MaterialTheme.typography.bodyMedium)
                            Text(label, color = color, style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold)
                        }
                        if (item.holding != true && item.note != null) {
                            Text(item.note, style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
                OutlinedButton(onClick = onCheck) { Text("Check again") }
            }
        }
    }

    @Composable
    private fun OrbotCard() {
        val installed = OrbotHelper.isInstalled(this)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Tor (via Orbot)", fontWeight = FontWeight.SemiBold)
                Text(
                    if (installed) "Orbot is installed. Going dark starts it; Orbot's " +
                        "VPN mode then routes all traffic over Tor."
                    else "Tor on Android is provided by Orbot. Install it to route this " +
                        "posture through Tor.",
                    style = MaterialTheme.typography.bodySmall
                )
                if (!installed) {
                    OutlinedButton(onClick = {
                        runCatching { startActivity(OrbotHelper.installIntent()) }
                            .onFailure { startActivity(OrbotHelper.installFallbackIntent()) }
                    }) { Text("Install Orbot") }
                }
            }
        }
    }

    @Composable
    private fun WgConfigCard(state: PostureUiState, onImport: () -> Unit) {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("WireGuard tunnel", fontWeight = FontWeight.SemiBold)
                Text(
                    if (state.wgConfigured) "Config imported — endpoint ${state.wgEndpoint}"
                    else "This posture tunnels all traffic. Import a WireGuard .conf " +
                        "(a commercial VPN or a VPS you control).",
                    style = MaterialTheme.typography.bodySmall
                )
                OutlinedButton(onClick = onImport) {
                    Text(if (state.wgConfigured) "Replace config" else "Import WireGuard config")
                }
            }
        }
    }

    @Composable
    private fun CapabilityRow(item: PostureItem) {
        val advisoryAction = if (item.action == PlannedAction.GUIDE_TO_SETTING)
            AdvisoryLinks.settingsActionFor(item.capability) else null
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(item.capability, fontWeight = FontWeight.SemiBold)
                        Text(item.summary, style = MaterialTheme.typography.bodySmall)
                        Text(item.reason, style = MaterialTheme.typography.labelSmall)
                    }
                    EnforcementBadge(item)
                }
                // Advisory = the app can't change it, but it can take you to the
                // OS setting that can.
                if (advisoryAction != null) {
                    TextButton(onClick = { openSetting(advisoryAction) }) {
                        Text("Open setting")
                    }
                }
            }
        }
    }

    private fun openSetting(action: String) {
        runCatching { startActivity(Intent(action)) }
            .onFailure { vm.setMessage("Couldn't open that setting on this device.") }
    }

    @Composable
    private fun EnforcementBadge(item: PostureItem) {
        val label = when (item.action) {
            PlannedAction.ENFORCE -> "enforced"
            PlannedAction.REQUEST_CONSENT -> "on consent"
            PlannedAction.NEEDS_TUNNEL -> "via tunnel"
            PlannedAction.NEEDS_ROOT -> "needs root"
            PlannedAction.GUIDE_TO_SETTING -> "advisory"
            PlannedAction.UNAVAILABLE -> "unavailable"
        }
        val color = when (item.enforcement) {
            Enforcement.ENFORCED -> MaterialTheme.colorScheme.primary
            Enforcement.ADVISORY -> MaterialTheme.colorScheme.tertiary
            Enforcement.UNAVAILABLE -> MaterialTheme.colorScheme.error
            else -> MaterialTheme.colorScheme.secondary
        }
        AssistChip(onClick = {}, label = { Text(label) },
            colors = AssistChipDefaults.assistChipColors(labelColor = color))
    }
}
