"""Ops HUD — Umbra's posture as an always-on status bar.

A thin, read-only bar you keep on screen while you work: the active posture and
score, whether the firewall is up, whether traffic is going through a VPN tunnel,
whether Tor is routing, what's exposed beyond loopback, and (opt-in) your public
IP. It is the glanceable face of the same audit `umbra audit` prints.

Three faces, one set of segments (`build_segments`):
  * `umbra hud`          — a GTK dock bar that refreshes itself (the always-on bar)
  * `umbra hud --once`   — one line for a tiling-WM bar (polybar / i3blocks / waybar)
  * `umbra hud --json`   — structured segments for a waybar custom module

Everything here except `run()` and `fetch_public_ip()` is pure and OS-independent,
so the segment logic is unit-tested without a desktop stack. `run()` lazy-imports
GTK, exactly like the tray, so importing this module works anywhere.

Read-only and root-optional (the audit degrades to N/A without privilege), so the
bar is safe to poll from the desktop.
"""

from __future__ import annotations

from dataclasses import dataclass

from umbra.auditmodel import AuditReport, Status

# --- pure core ---------------------------------------------------------------

# ANSI SGR codes for `--once` (terminal / text bars), per status.
_ANSI = {
    Status.OK: "32",     # green
    Status.WARN: "33",   # yellow
    Status.FAIL: "31",   # red
    Status.INFO: "90",   # bright black (dim)
    Status.NA: "90",
}
# Pango/GTK hexes for the dock bar, tuned to read on a dark panel.
_HEX = {
    Status.OK: "#8ae234",
    Status.WARN: "#fce94f",
    Status.FAIL: "#ef2929",
    Status.INFO: "#888a85",
    Status.NA: "#888a85",
}
_GLYPH = {
    Status.OK: "●",
    Status.WARN: "▲",
    Status.FAIL: "✗",
    Status.INFO: "·",
    Status.NA: "–",
}


@dataclass
class Segment:
    """One field of the bar: a short label, a short value, and a status colour."""
    label: str
    value: str
    status: Status


def _check(report: AuditReport, cid: str):
    return next((c for c in report.checks if c.id == cid), None)


def _score_status(score: int | None) -> Status:
    if score is None:
        return Status.NA
    if score >= 90:
        return Status.OK
    if score >= 60:
        return Status.WARN
    return Status.FAIL


def _cap_segment(report: AuditReport, label: str, token: str) -> Segment:
    """A segment from a required-capability check (`require:<token>`).

    Absent means the active profile doesn't promise this capability, so we show a
    neutral n/a rather than implying it failed.
    """
    c = _check(report, f"require:{token}")
    if c is None:
        return Segment(label, "n/a", Status.INFO)
    value = {Status.OK: "on", Status.WARN: "drift",
             Status.FAIL: "off", Status.NA: "n/a", Status.INFO: "n/a"}[c.status]
    return Segment(label, value, c.status)


def _vpn_segment(report: AuditReport) -> Segment:
    """Live tunnel state, from the default-route probe, with the promised-but-down
    case (a profile that requires wireguard whose route isn't up) shown as FAIL."""
    req = _check(report, "require:wireguard")
    if req is not None and req.status is Status.FAIL:
        return Segment("vpn", "down", Status.FAIL)
    if req is not None and req.status is Status.OK:
        return Segment("vpn", "up", Status.OK)       # route + killswitch verified
    route = _check(report, "route")
    if route is not None and route.status is Status.OK:
        return Segment("vpn", "up", Status.OK)
    return Segment("vpn", "off", Status.INFO)


def _tor_segment(report: AuditReport) -> Segment:
    """Tor routing. Absent = this profile doesn't route through Tor (off, neutral).
    NA = it does, but this reader can't verify it (e.g. the nft killswitch needs
    root and HUD access isn't enabled) -- say n/a, never claim "off"."""
    c = _check(report, "require:tor")
    if c is None:
        return Segment("tor", "off", Status.INFO)
    if c.status is Status.OK:
        return Segment("tor", "on", Status.OK)
    if c.status in (Status.NA, Status.INFO):
        return Segment("tor", "n/a", Status.NA)
    return Segment("tor", "off", c.status)


def _exposure_segment(report: AuditReport) -> Segment:
    c = _check(report, "exposure")
    if c is None:
        return Segment("net", "n/a", Status.NA)
    if c.status is Status.OK:
        return Segment("net", "clear", Status.OK)
    if c.status is Status.NA:
        return Segment("net", "n/a", Status.NA)
    # WARN: evidence looks like "reachable: 0.0.0.0:22, [::]:631"
    n = len([p for p in c.evidence.split(":", 1)[-1].split(",") if p.strip()]) \
        if ":" in c.evidence else 0
    return Segment("net", f"{n} open" if n else "open", Status.WARN)


def build_segments(report: AuditReport, active: str | None,
                   public_ip: str | None = None) -> list[Segment]:
    """The ordered fields of the bar, derived from an audit report.

    `public_ip` is included as a segment only when provided (the caller opts in;
    fetching it contacts an external service — see `fetch_public_ip`).
    """
    score = report.score()
    segs = [
        # No marker = nothing applied = the `normal` profile (never "stock").
        Segment("umbra", active or "normal", Status.OK if active else Status.INFO),
        Segment("score", "n/a" if score is None else f"{score}", _score_status(score)),
        _cap_segment(report, "fw", "firewall"),
        _vpn_segment(report),
        _tor_segment(report),
        _exposure_segment(report),
    ]
    if public_ip is not None:
        segs.append(Segment("ip", public_ip, Status.INFO))
    return segs


def render_line(segments: list[Segment], color: bool = True) -> str:
    """A single line for a text bar (polybar/i3blocks) or `--once` on a terminal."""
    parts = []
    for s in segments:
        glyph = _GLYPH[s.status]
        if color:
            code = _ANSI[s.status]
            parts.append(f"\x1b[{code}m{glyph}\x1b[0m {s.label} "
                         f"\x1b[1;{code}m{s.value}\x1b[0m")
        else:
            parts.append(f"{glyph} {s.label} {s.value}")
    return "   ".join(parts)


def render_json(segments: list[Segment], active: str | None,
                score: int | None) -> str:
    import json
    return json.dumps({
        "active": active,
        "score": score,
        "segments": [{"label": s.label, "value": s.value, "status": s.status.value}
                     for s in segments],
    })


def _worst_class(segments: list[Segment]) -> str:
    """The CSS class a waybar module should carry: the loudest status wins, so a
    single failing control can turn the whole module red via stylesheet."""
    statuses = {s.status for s in segments}
    if Status.FAIL in statuses:
        return "fail"
    if Status.WARN in statuses:
        return "warn"
    return "ok"


def render_waybar(segments: list[Segment], active: str | None,
                  score: int | None) -> str:
    """A waybar custom-module object: `{text, tooltip, class, percentage}`.

    `text` is Pango markup (waybar renders it), `class` lets a stylesheet colour
    the module by worst status, and `percentage` exposes the score for a bar.
    """
    import json
    from html import escape
    tooltip = "\n".join([f"umbra posture: {active or 'normal'}"]
                        + [f"{s.label}: {s.value}" for s in segments])
    obj = {
        "text": render_markup(segments),
        "tooltip": escape(tooltip),
        "class": _worst_class(segments),
    }
    if score is not None:
        obj["percentage"] = score
    return json.dumps(obj)


def render_markup(segments: list[Segment]) -> str:
    """Pango markup for the GTK dock bar (one label, colour per segment)."""
    from html import escape
    parts = []
    for s in segments:
        hexc = _HEX[s.status]
        parts.append(
            f'<span foreground="{hexc}">{escape(_GLYPH[s.status])}</span> '
            f'<span foreground="#c7c7c7">{escape(s.label)}</span> '
            f'<span foreground="{hexc}" weight="bold">{escape(s.value)}</span>')
    return "     ".join(parts)


# --- public IP (opt-in; contacts an external service) ------------------------

def fetch_public_ip(timeout: float = 4.0) -> str | None:
    """Best-effort public IP via a plain-text endpoint. Returns None on any error.

    This makes an outbound request, so it is only ever called when the user passes
    `--public-ip`. When a VPN/Tor tunnel is up, this reports the *exit* IP — which
    is exactly what you want to eyeball on the bar.
    """
    import urllib.request
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as resp:
            ip = resp.read().decode("ascii", "ignore").strip()
        return ip or None
    except Exception:
        return None


# --- GTK bar -----------------------------------------------------------------

def run(profile: str | None = None, dock: str | None = None, interval: int = 5,
        public_ip: bool = False, profiles_dir: str | None = None) -> int:
    """Start the always-on bar. Returns non-zero with a hint if GTK is absent.

    Default (`dock=None`) is a **floating** window: draggable by its titlebar,
    resizable from its borders, kept above and shown on every workspace — so you
    can park it wherever it doesn't collide with your panel. `dock="top"` /
    `dock="bottom"` pins it to a screen edge as a borderless strut bar instead
    (for a bare WM with a free edge).
    """
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
    except (ImportError, ValueError) as exc:
        print("umbra hud needs a desktop GUI stack (PyGObject + GTK 3).")
        print("  Debian/Kali:  sudo apt install python3-gi gir1.2-gtk-3.0")
        print(f"  ({exc})")
        print("  (headless? use  umbra hud --once  in polybar/i3blocks, or  --waybar  in waybar)")
        return 1

    from umbra import snapshots
    from umbra.audit import run_audit
    from umbra.profiles import load_profile
    from umbra.runner import Runner

    runner = Runner(dry_run=False)

    # Fetch the public IP at most every ~30s even if the bar refreshes faster, so
    # an opt-in convenience never becomes a chatty outbound beacon.
    ip_state = {"ip": None, "ticks": 0}
    ip_every = max(1, 30 // max(1, interval))

    def current_segments():
        active = snapshots.active_profile()
        # Audit what the label says: the active profile (or `normal` when none).
        target = profile or active or "normal"
        report = run_audit(runner, load_profile(target, profiles_dir))
        ip = None
        if public_ip:
            if ip_state["ticks"] % ip_every == 0:
                ip_state["ip"] = fetch_public_ip()
            ip_state["ticks"] += 1
            ip = ip_state["ip"] or "?"
        return build_segments(report, active, public_ip=ip)

    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    geo = monitor.get_geometry()
    height = 28

    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    win.set_title("umbra hud")
    win.set_keep_above(True)
    win.stick()                                        # visible on every workspace
    win.override_background_color(
        Gtk.StateFlags.NORMAL, Gdk.RGBA(0.06, 0.06, 0.07, 0.92))

    label = Gtk.Label()
    label.set_halign(Gtk.Align.START)
    label.set_valign(Gtk.Align.CENTER)
    label.set_margin_start(10)
    label.set_margin_end(10)

    if dock in ("top", "bottom"):
        # Pinned strut bar: borderless, full width, reserves its edge.
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.DOCK)
        win.set_default_size(geo.width, height)
        win.move(geo.x, geo.y if dock == "top" else geo.y + geo.height - height)
        win.add(label)

        def reserve_strut(*_):
            """Best-effort: keep maximised windows from covering the bar (X11 only)."""
            try:
                gdk_win = win.get_window()
                atom = Gdk.Atom.intern("_NET_WM_STRUT_PARTIAL", False)
                card = Gdk.Atom.intern("CARDINAL", False)
                top = height if dock == "top" else 0
                bottom = 0 if dock == "top" else height
                struts = [0, 0, top, bottom,
                          0, 0, 0, 0,
                          geo.x if dock == "top" else 0,
                          geo.x + geo.width - 1 if dock == "top" else 0,
                          geo.x if dock == "bottom" else 0,
                          geo.x + geo.width - 1 if dock == "bottom" else 0]
                Gdk.property_change(gdk_win, atom, card, 32,
                                    Gdk.PropMode.REPLACE, struts, len(struts))
            except Exception:
                pass  # Wayland or a stripped Gdk: fall back to keep-above only.

        win.connect("realize", reserve_strut)
    else:
        # Floating: a normal window you can drag (titlebar) and resize (borders).
        win.set_decorated(True)
        win.set_resizable(True)
        win.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        win.set_default_size(560, height)
        # Park it clear of a top panel; the WM may still choose its own spot.
        win.move(geo.x + 80, geo.y + 80)
        # Also drag from anywhere on the body, so it moves even undecorated.
        ebox = Gtk.EventBox()
        ebox.add(label)
        ebox.connect(
            "button-press-event",
            lambda w, e: win.begin_move_drag(e.button, int(e.x_root), int(e.y_root), e.time)
            if e.button == 1 else None)
        win.add(ebox)

    def refresh():
        try:
            label.set_markup(render_markup(current_segments()))
        except Exception as exc:                       # never let a probe kill the bar
            label.set_markup(f'<span foreground="#ef2929">umbra hud: {exc}</span>')
        return True

    refresh()
    GLib.timeout_add_seconds(max(1, interval), refresh)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0
