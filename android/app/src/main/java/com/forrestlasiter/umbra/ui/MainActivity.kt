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
import com.forrestlasiter.umbra.vpn.UmbraVpnService

class MainActivity : ComponentActivity() {

    private val vm: PostureViewModel by viewModels()

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

        // VPN consent: the OS asks the user once; only then may we start the tunnel.
        val consent = rememberLauncherForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                UmbraVpnService.start(this, state.selected)
                vm.setActive(true)
            }
        }

        fun activate() {
            val prepare: Intent? = VpnService.prepare(this)
            if (prepare != null) consent.launch(prepare)
            else { UmbraVpnService.start(this, state.selected); vm.setActive(true) }
        }

        fun deactivate() { UmbraVpnService.stop(this); vm.setActive(false) }

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

            // Profile picker
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                state.profileNames.forEachIndexed { i, name ->
                    SegmentedButton(
                        selected = name == state.selected,
                        onClick = { vm.select(name) },
                        shape = SegmentedButtonDefaults.itemShape(i, state.profileNames.size),
                    ) { Text(name) }
                }
            }

            // Activate / deactivate
            Button(
                onClick = { if (state.active) deactivate() else activate() },
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (state.active) "Deactivate" else "Go dark: ${state.selected}") }

            HorizontalDivider()
            Text("What ${state.selected} means on this device",
                style = MaterialTheme.typography.titleMedium)

            state.plan?.items?.forEach { CapabilityRow(it) }
        }
    }

    @Composable
    private fun CapabilityRow(item: PostureItem) {
        Card(Modifier.fillMaxWidth()) {
            Row(
                Modifier.fillMaxWidth().padding(12.dp),
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
        }
    }

    @Composable
    private fun EnforcementBadge(item: PostureItem) {
        // Text label, never colour alone (accessibility) — and never a fake "on".
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
