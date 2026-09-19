"""A tiny live posture dashboard server (stdlib only, no new deps).

`umbra dashboard` runs this: each page load re-runs the audit and serves the
accessible HTML dashboard, so you get a live view instead of a point-in-time
file. Bound to localhost. Needs root to measure (same as `umbra audit`).

Refresh is a plain link (not a forced meta-refresh), so it doesn't trip the
WCAG timing criteria - the viewer decides when to re-check.
"""

from __future__ import annotations

import http.server
import socketserver

from umbra.audit import run_audit
from umbra.profiles import load_profile
from umbra.report import render_html
from umbra.runner import Runner


def _handler_class(profile_name: str, runner: Runner):
    profile = load_profile(profile_name)

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib naming)
            if self.path.split("?", 1)[0] not in ("/", "/index.html"):
                self.send_error(404, "not found")
                return
            report = run_audit(runner, profile)
            body = render_html(report, live=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence per-request logging
            pass

    return DashboardHandler


def serve(profile_name: str, port: int, runner: Runner, host: str = "127.0.0.1") -> None:
    handler = _handler_class(profile_name, runner)
    with socketserver.TCPServer((host, port), handler) as httpd:
        print(f"umbra dashboard for '{profile_name}' -> http://{host}:{port}  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
