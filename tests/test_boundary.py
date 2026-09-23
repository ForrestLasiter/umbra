"""The platform boundary, enforced in code.

Phase 16 split the brain (platform-agnostic core) from the hands (the Linux
agent). This test makes that boundary real: the CORE must be usable without
dragging in any Linux enforcement machinery, so the same core can back the
Android/iOS adapters (which is the whole point).

Two checks:
  1. Runtime: importing the core (umbra.spec, which pulls the rest of the core)
     must NOT import any enforcement module.
  2. Source: no core module may import an enforcement module directly.

If you genuinely need to cross the line, move the shared piece INTO the core --
don't make the core depend on the agent.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "umbra"

# The platform-agnostic core: the posture model, profiles, capabilities, the
# enforcement matrix, the spec export, and HTML rendering. (base.py + runner.py
# are shared infrastructure the model references and are allowed.)
CORE = ["profiles", "capabilities", "platform", "spec", "report", "auditmodel",
        "model", "validate", "paths"]

# The Linux agent: everything that measures or mutates the machine. The core must
# never import any of these.
ENFORCEMENT = {
    "umbra.engine", "umbra.snapshots", "umbra.restore", "umbra.fsutil",
    "umbra.lock", "umbra.cli", "umbra.tray", "umbra.server", "umbra.doctor",
    "umbra.audit",
    "umbra.modules.netdark", "umbra.modules.telemetry", "umbra.modules.rf",
    "umbra.modules.tunnel", "umbra.modules.kernel", "umbra.modules.identity",
}


def test_importing_the_core_pulls_in_no_enforcement_module():
    # A fresh interpreter so no earlier test's imports pollute sys.modules.
    code = (
        "import umbra.spec, umbra.platform, umbra.capabilities, umbra.profiles, umbra.report;"
        "import sys, json;"
        f"forbidden={sorted(ENFORCEMENT)!r};"
        "print(json.dumps([m for m in forbidden if m in sys.modules]))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    leaked = out.stdout.strip().splitlines()[-1]
    import json
    assert json.loads(leaked) == [], f"core imported enforcement modules: {leaked}"


@pytest.mark.parametrize("mod", CORE)
def test_core_module_does_not_import_enforcement_directly(mod):
    src = (PKG / f"{mod}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    bad = imported & ENFORCEMENT
    assert not bad, f"core module umbra.{mod} imports enforcement: {bad}"
