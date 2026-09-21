"""Packaging lint — cross-platform checks on the installer/service files.

These can't install anything here (that's validated on Kali), but they guard the
important invariants so a careless edit can't break the install contract.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_POLICY = "packaging/com.forrestlasiter.umbra.policy"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_polkit_policy_is_valid_xml_with_exec_action():
    root = ET.fromstring(_read(_POLICY))
    action = root.find("action")
    assert action is not None and action.get("id") == "com.forrestlasiter.umbra.run"
    annotations = {a.get("key"): a.text for a in action.findall("annotate")}
    assert annotations["org.freedesktop.policykit.exec.path"] == "/usr/bin/umbra"


def test_installers_and_deb_ship_the_polkit_policy():
    assert "/usr/share/polkit-1/actions" in _read("install.sh")
    assert "com.forrestlasiter.umbra.policy" in _read("install.sh")
    assert "/usr/bin/umbra" in _read("install.sh")                 # exec.path target
    assert "com.forrestlasiter.umbra.policy" in _read("uninstall.sh")
    assert "com.forrestlasiter.umbra.policy" in _read("packaging/build-deb.sh")


def test_installer_creates_wrapper_and_uses_pythonpath():
    sh = _read("install.sh")
    assert "/usr/local/bin/umbra" in sh
    assert "python3 -m umbra.cli" in sh
    assert "PYTHONPATH" in sh
    assert "--with-boot-service" in sh
    # `sudo umbra` must resolve even where secure_path lacks /usr/local/bin.
    assert "/usr/sbin/umbra" in sh


def test_uninstaller_removes_both_wrapper_locations():
    sh = _read("uninstall.sh")
    assert "/usr/local/bin/umbra" in sh and "/usr/sbin/umbra" in sh


def test_uninstaller_restores_posture_before_removing_code():
    sh = _read("uninstall.sh")
    # `umbra normal` must appear before the code is deleted, or uninstalling
    # could strand the machine in a dark state.
    normal_at = sh.find("umbra normal")
    remove_at = sh.find("rm -rf /opt/umbra")
    assert normal_at != -1 and remove_at != -1
    assert normal_at < remove_at


def test_boot_service_is_a_oneshot_that_applies_and_reverts():
    unit = _read("packaging/umbra-boot.service")
    assert "Type=oneshot" in unit
    assert "apply" in unit and "boot-profile" in unit
    # method-agnostic: bare `umbra` via sh -c works for both .deb and install.sh
    assert "ExecStop=/bin/sh -c 'umbra normal'" in unit
    exec_lines = [ln for ln in unit.splitlines() if ln.startswith("Exec")]
    assert exec_lines and not any("/usr/local/bin" in ln for ln in exec_lines)
    assert "WantedBy=multi-user.target" in unit


def test_deb_builder_declares_deps_and_restores_on_remove():
    sh = _read("packaging/build-deb.sh")
    assert "Depends: python3, python3-yaml, python3-jsonschema, nftables" in sh
    assert "PYTHONPATH=/usr/lib/umbra" in sh          # deb code layout
    assert "/usr/bin/umbra" in sh                     # wrapper in secure_path
    # prerm must restore posture before removal
    prerm_at = sh.find("prerm")
    normal_at = sh.find("/usr/bin/umbra normal")
    assert prerm_at != -1 and normal_at != -1 and normal_at > prerm_at
