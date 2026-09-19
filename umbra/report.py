"""Render an audit report as a self-contained, accessible HTML dashboard.

Design targets WCAG 2.1 AA from the start:
  * one <html lang>, one <h1>, logical headings, landmark regions;
  * status conveyed by icon + TEXT label, never colour alone (SC 1.4.1);
  * AA contrast in both dark and light themes;
  * :focus-visible rings, reduced-motion honoured, a skip link;
  * a real <table> with <th scope> for the checks.

Pure function: render_html(report) -> str. No I/O, so it is easy to unit-test.
"""

from __future__ import annotations

import html

from umbra.audit import AuditReport, Status

# Icon + accessible word for each status. The word means the colour is never the
# only signal (SC 1.4.1).
_STATUS_META = {
    Status.OK.value:   ("●", "OK"),      # ●
    Status.WARN.value: ("▲", "Warning"),  # ▲
    Status.FAIL.value: ("✕", "Fail"),     # ✕
    Status.INFO.value: ("◆", "Info"),     # ◆
    Status.NA.value:   ("○", "N/A"),      # ○
}

_CSS = """\
:root{
  --bg:#0f1419; --surface:#1a2028; --surface-2:#212a34; --text:#e6edf3;
  --muted:#9aa7b4; --border:#2b333d; --accent:#7aa2ff;
  --ok:#56d68a; --warn:#e3b341; --fail:#ff7b72; --info:#79b8ff; --na:#8b95aa;
}
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    --bg:#ffffff; --surface:#f5f7fa; --surface-2:#eef1f5; --text:#1a2028;
    --muted:#55606b; --border:#d5dbe2; --accent:#0b5cad;
    --ok:#0b7a57; --warn:#7a5b00; --fail:#b3261e; --info:#0b5cad; --na:#5b6570;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1419; --surface:#1a2028; --surface-2:#212a34; --text:#e6edf3;
  --muted:#9aa7b4; --border:#2b333d; --accent:#7aa2ff;
  --ok:#56d68a; --warn:#e3b341; --fail:#ff7b72; --info:#79b8ff; --na:#8b95aa;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 16px}
a{color:var(--accent)}
.skip-link{position:absolute;left:-999px;top:0;background:var(--surface);
  color:var(--text);padding:8px 12px;border:1px solid var(--border);border-radius:6px}
.skip-link:focus{left:8px;top:8px;z-index:10}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
:focus:not(:focus-visible){outline:none}
header.page{border-bottom:1px solid var(--border);padding-bottom:16px;margin-bottom:20px}
h1{font-size:1.6rem;margin:0 0 4px}
.meta{color:var(--muted);font-size:.9rem}
.summary{list-style:none;display:flex;flex-wrap:wrap;gap:10px;padding:0;margin:18px 0 24px}
.summary li{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:8px 12px;display:flex;align-items:center;gap:8px;font-size:.92rem}
.count{font-weight:700;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;overflow:hidden}
caption{text-align:left;color:var(--muted);font-size:.9rem;margin-bottom:8px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top}
thead th{background:var(--surface-2);font-size:.82rem;text-transform:uppercase;
  letter-spacing:.03em;color:var(--muted)}
tbody tr:last-child td{border-bottom:0}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:600;white-space:nowrap}
.badge .ico{font-size:.9em}
.st-ok{color:var(--ok)} .st-warn{color:var(--warn)} .st-fail{color:var(--fail)}
.st-info{color:var(--info)} .st-na{color:var(--na)}
.evidence{color:var(--text)} .rec{color:var(--muted);font-size:.9rem}
.cat{color:var(--muted);font-size:.85rem;text-transform:capitalize}
footer{color:var(--muted);font-size:.85rem;margin-top:24px;
  border-top:1px solid var(--border);padding-top:14px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media (prefers-reduced-motion: reduce){*,*::before,*::after{
  animation-duration:.001ms!important;transition-duration:.001ms!important}}
"""


def _badge(status: Status) -> str:
    icon, word = _STATUS_META[status.value]
    cls = f"st-{status.value}"
    return (f'<span class="badge {cls}"><span class="ico" aria-hidden="true">{icon}</span>'
            f'<span>{html.escape(word)}</span></span>')


def render_html(report: AuditReport) -> str:
    counts = report.counts()
    summary_items = "".join(
        f'<li>{_badge(Status(s))}<span class="count">{counts[s]}</span></li>'
        for s in ("ok", "warn", "fail", "info", "na")
    )

    rows = ""
    for c in report.checks:
        rec = f'<div class="rec">{html.escape(c.recommendation)}</div>' if c.recommendation else ""
        rows += (
            "<tr>"
            f'<td>{_badge(c.status)}</td>'
            f'<th scope="row">{html.escape(c.title)}</th>'
            f'<td class="cat">{html.escape(c.category)}</td>'
            f'<td><div class="evidence">{html.escape(c.evidence)}</div>{rec}</td>'
            "</tr>"
        )

    profile = html.escape(report.profile)
    generated = html.escape(report.generated_at)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Umbra posture — {profile}</title>
<style>{_CSS}</style>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<div class="wrap">
<header class="page">
  <h1>Umbra posture dashboard</h1>
  <p class="meta">Profile <strong>{profile}</strong> · generated {generated} (UTC)</p>
</header>
<main id="main">
  <h2 class="sr-only">Summary</h2>
  <ul class="summary" aria-label="Result counts by status">{summary_items}</ul>
  <h2 class="sr-only">Checks</h2>
  <table>
    <caption>Each check is a read-only probe of the live machine.</caption>
    <thead>
      <tr><th scope="col">Status</th><th scope="col">Check</th>
          <th scope="col">Category</th><th scope="col">Evidence &amp; recommendation</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</main>
<footer>
  <p>Umbra — a privacy/anonymity/hardening posture engine. This report reflects
  the machine state at generation time; re-run <code>umbra audit</code> to refresh.</p>
</footer>
</div>
</body>
</html>
"""
