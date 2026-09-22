"""Where Umbra reads profiles/schema from and writes runtime state to.

Kept in one place so there is a single answer to "where does that file live?".
During development we run straight out of the repo; once installed as a system
package the state dir moves under /var/lib. The env var override makes tests and
dry-runs point at a scratch directory instead of touching the real one.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

# The repo root = two levels up from this file (umbra/paths.py -> repo/).
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Static, read-only inputs SHIP INSIDE the package (umbra/profiles, umbra/schema)
# and are located via importlib.resources, so they resolve identically from a
# source checkout, a wheel install, and the .deb.
_PKG_DIR = Path(str(resources.files("umbra")))
PROFILES_DIR = _PKG_DIR / "profiles"
SCHEMA_DIR = _PKG_DIR / "schema"
PROFILE_SCHEMA = SCHEMA_DIR / "profile.schema.json"


def state_dir() -> Path:
    """Directory that holds transaction snapshots (spec §4).

    Resolution order:
      1. $UMBRA_STATE_DIR   -- tests/dry-runs point this at a temp dir
      2. /var/lib/umbra     -- when running as an installed system service
      3. <repo>/engine/state -- the dev default
    """
    override = os.environ.get("UMBRA_STATE_DIR")
    if override:
        return Path(override)
    system = Path("/var/lib/umbra")
    if system.parent.exists() and os.access(system.parent, os.W_OK):
        return system
    return _REPO_ROOT / "engine" / "state"


def transactions_dir() -> Path:
    return state_dir() / "transactions"
