"""Render Umbra's posture as Conky-friendly text.

Conky's `${execpi <secs> umbra conky}` runs this and parses the output for Conky
markup, so we emit a compact, colourised widget: the active posture, the audit
score, and a tick/cross per required capability. `--field NAME` instead prints a
single value for people composing their own conkyrc with `${execi}`.

Read-only and root-optional (the audit degrades to N/A without privilege), so it
is safe to poll from the desktop.
"""

from __future__ import annotations

from umbra.auditmodel import AuditReport, Status

# Conky colour hexes (no leading #). Tuned to read on a dark desktop.
_STATUS_COLOR = {
    Status.OK: "8ae234",
    Status.WARN: "fce94f",
    Status.FAIL: "ef2929",
    Status.INFO: "888a85",
    Status.NA: "888a85",
}
_STATUS_GLYPH = {
    Status.OK: "✓",    # ✓
    Status.WARN: "!",
    Status.FAIL: "✗",  # ✗
    Status.INFO: "·",  # ·
    Status.NA: "–",    # –
}
_ACCENT = "729fcf"
_DIM = "888a85"


def _c(color: str, text: str, enabled: bool) -> str:
    """Wrap text in a Conky colour object (or leave it plain)."""
    return f"${{color {color}}}{text}${{color}}" if enabled else text


def _score_color(score: int | None) -> str:
    if score is None:
        return _DIM
    if score >= 90:
        return "8ae234"
    if score >= 60:
        return "fce94f"
    return "ef2929"


def _required(report: AuditReport) -> list[tuple[str, Status]]:
    out = []
    for c in report.checks:
        if c.id.startswith("require:"):
            out.append((c.id.split(":", 1)[1], c.status))
    return out


def render_block(report: AuditReport, active: str | None, color: bool = True) -> str:
    """The full multi-line Conky widget."""
    score = report.score()
    score_str = "n/a" if score is None else f"{score}/100"

    header = (
        _c(_ACCENT, "◐ umbra", color)
        + "  " + _c(_DIM, "posture", color) + " " + (active or "none")
        + "  " + _c(_DIM, "score", color) + " " + _c(_score_color(score), score_str, color)
    )
    lines = [header]

    reqs = _required(report)
    if reqs:
        for name, status in reqs:
            glyph = _c(_STATUS_COLOR[status], _STATUS_GLYPH[status], color)
            lines.append(f"  {glyph} {name}")

    # One compact probe line: is anything reachable beyond loopback?
    exposure = next((c for c in report.checks if c.id == "exposure"), None)
    if exposure is not None:
        glyph = _c(_STATUS_COLOR[exposure.status], _STATUS_GLYPH[exposure.status], color)
        lines.append(f"  {glyph} {exposure.evidence or exposure.title}")

    return "\n".join(lines)


def field(report: AuditReport, active: str | None, name: str) -> str:
    """A single value, for `${execi N umbra conky --field NAME}`."""
    counts = report.counts()
    score = report.score()
    if name == "profile":
        return report.profile
    if name == "active":
        return active or "none"
    if name == "score":
        return "" if score is None else str(score)
    if name in counts:                      # ok / warn / fail / info / na
        return str(counts[name])
    if name == "tor":
        tor = next((c for c in report.checks if c.id == "require:tor"), None)
        return tor.status.value if tor else "na"
    raise KeyError(name)
