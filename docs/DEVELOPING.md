# Developing Umbra

## Setup

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
umbra --help
pytest -q
```

## How the pieces fit (read in this order)

1. **`umbra/profiles.py`** — turns a YAML file into a validated `Profile`
   (resolves `extends`, checks it against `schema/profile.schema.json`).
2. **`umbra/modules/base.py`** — the contract every layer implements:
   `measure → plan → apply → verify → restore`.
3. **`umbra/modules/netdark.py` / `telemetry.py`** — the two real Phase-1
   modules. Read these to see the pattern; `rf.py` / `tunnel.py` are Phase-2 stubs.
4. **`umbra/runner.py`** — every external command goes through here, so dry-run
   and logging are uniform. `read_only=True` probes always run; mutations respect
   `--dry-run`.
5. **`umbra/snapshots.py`** — crash-safe transactions. A control's prior state is
   written *before* it is changed; a run is durable only once `manifest.json` is
   committed.
6. **`umbra/restore.py`** — the closed set of restore primitives. Restore is
   *data, not code*.
7. **`umbra/engine.py`** — orders the modules, wraps a run in one transaction,
   recovers crashed runs, handles fail modes.

## Running off-Linux (this dev machine)

The CLI is import-clean and safe on Windows/macOS. Because `nft`, `systemctl`,
`/etc/hosts` etc. are absent, `measure()` reports `UNKNOWN` and `plan` finds
nothing actionable. Use it to exercise profile loading, `plan`, `status --json`,
and `--dry-run`. Real behaviour is verified on the Kali box.

## Verifying on Kali (the real test)

> Do this in a VM or a machine you can recover, since netdark replaces the
> nftables ruleset. `umbra normal` and `umbra restore` bring it back.

```bash
sudo umbra status home           # expect real OK/-> per control
sudo umbra plan travel           # see the actions
sudo umbra --dry-run apply home  # dry-run first
sudo umbra apply home            # then for real
sudo umbra audit home            # prove it: listening sockets, default route
sudo umbra normal                # restore to stock
```

Checks that matter after `apply home`:
- `sudo nft list ruleset` shows the `inet umbra` table with `policy drop`.
- `ping <this host>` from another LAN device times out (stealth).
- `systemctl is-active avahi-daemon` is `inactive`.
- `sysctl net.ipv6.conf.all.use_tempaddr` is `2`.
- `grep umbra /etc/hosts` shows the sinkhole block.
Then `sudo umbra normal` and confirm every one of the above reverts.

## Conventions

- Keep every system-changing call behind `runner.run(..., read_only=False)`.
- Snapshot **before** you mutate; store the *full* prior value, not a delta.
- New restore behaviour = a new named primitive in `restore.py`, never an inline
  shell string in a snapshot.
