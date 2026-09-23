import SwiftUI
import UmbraCore

/// The whole iOS front-end: pick a posture, see honestly what this device can
/// keep. Every capability shows its real level as text — never a fake "on".
struct ContentView: View {
    @State private var spec: CoreSpec?
    @State private var selected = "travel"
    @State private var error: String?

    private var profileNames: [String] {
        (spec?.profiles.keys.filter { $0 != "normal" } ?? []).sorted()
    }

    private var plan: PosturePlan? {
        guard let spec else { return nil }
        return PostureEngine.plan(spec: spec, profile: selected)
    }

    var body: some View {
        NavigationStack {
            Group {
                if let error {
                    Text(error).foregroundStyle(.red).padding()
                } else {
                    content
                }
            }
            .navigationTitle("Umbra")
        }
        .onAppear(perform: load)
    }

    private var content: some View {
        List {
            Section {
                Picker("Posture", selection: $selected) {
                    ForEach(profileNames, id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.segmented)

                Text("This device enforces what it honestly can via the Network "
                     + "Extension and tells you the rest — it does not pretend to "
                     + "be the Linux build.")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            if let plan {
                Section("What \(selected) means on this device") {
                    ForEach(plan.items) { CapabilityRow(item: $0) }
                }
            }
        }
    }

    private func load() {
        do {
            let loaded = try CoreSpec.loadBundled()
            spec = loaded
            if !loaded.profiles.keys.contains(selected) {
                selected = profileNames.first ?? "travel"
            }
        } catch {
            self.error = "Could not load core spec: \(error.localizedDescription)"
        }
    }
}

private struct CapabilityRow: View {
    let item: PostureItem

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.capability).font(.headline)
                Text(item.summary).font(.subheadline)
                Text(item.reason).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(badge).font(.caption.bold()).foregroundStyle(tint)
        }
    }

    private var badge: String {
        switch item.action {
        case .enforce: return "enforced"
        case .requestEntitlement: return "on grant"
        case .needsTunnel: return "via tunnel"
        case .needsRoot: return "needs root"
        case .guideToSetting: return "advisory"
        case .unavailable: return "unavailable"
        }
    }

    private var tint: Color {
        switch item.enforcement {
        case .enforced: return .green
        case .advisory: return .orange
        case .unavailable: return .red
        default: return .blue
        }
    }
}
