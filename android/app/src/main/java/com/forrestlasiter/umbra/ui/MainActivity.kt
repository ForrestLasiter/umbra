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
import com.forrestlasiter.umbra.vpn.SinkholeStats
import com.forrestlasiter.umbra.vpn.TunnelController

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
            val prepare: Intent? = VpnService.prepare(this)
            if (prepare != null) consent.launch(prepare) else startEnforcement(state)
        }

        fun deactivate() {
            state.plan?.let { tunnels.deactivate(it) }
            vm.setActive(false)
        }

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

            // WireGuard config: needed by tunnel postures. Bring your own endpoint.
            val needsWg = state.plan?.items?.any {
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

            HorizontalDivider()
            Text("What ${state.selected} means on this device",
                style = MaterialTheme.typography.titleMedium)
            state.plan?.items?.forEach { CapabilityRow(it) }
        }
    }

    private fun startEnforcement(state: PostureUiState) {
        val plan = state.plan ?: return
        val error = tunnels.activate(state.selected, plan)
        if (error == null) { vm.setActive(true); vm.setMessage("Enforcing ${state.selected}.") }
        else vm.setMessage(error)
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
