"""nftread — read the live nftables ruleset, with or without root.

Why this exists
---------------
The kernel only lets root read firewall rules. `umbra audit` under sudo is
fine, but the HUD, `umbra conky`, and a plain `umbra status` run as your normal
user -- and a GUI must never run as root. Before this helper, an unprivileged
read failed silently, the probe saw empty output, and the firewall/killswitch
were reported as DRIFT ("off") while they were actually up.

The fix is privilege *separation*, not privilege *escalation* of the HUD:

  * root          -> run `nft list ruleset` directly.
  * normal user   -> ask sudo, non-interactively (`-n`), to run EXACTLY
                     `/usr/sbin/nft list ruleset`. That one read-only command is
                     whitelisted by /etc/sudoers.d/umbra-hud (opt-in:
                     sudo umbra-hud-access enable). sudo itself compares the full
                     argv, so `nft -f ...` or `nft flush ...` are still refused.

`-n` means sudo never prompts: if the rule isn't installed it fails instantly
with "a password is required" instead of hanging the HUD waiting for input.

Callers must treat a failed read (`not result.ok`) as UNKNOWN -- "couldn't
look" -- never as "the firewall is down".
"""

from __future__ import annotations

import os

from umbra.runner import RunResult, Runner

# Must match the path in packaging/umbra-hud.sudoers character for character:
# sudo matches the command path literally, so a different spelling (/sbin/nft)
# would not be covered by the rule.
NFT_PATH = "/usr/sbin/nft"

UNREADABLE_HINT = (
    "can't read the firewall without root -- run with sudo, or enable HUD "
    "access: sudo umbra-hud-access enable"
)


def _is_root() -> bool:
    # os.geteuid doesn't exist on Windows (where the unit tests also run), so
    # treat "unknown" as not-root rather than crashing.
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def list_ruleset(runner: Runner) -> RunResult:
    """Return the result of reading the full ruleset.

    Check `.available` (is the tool installed?) and `.ok` (did the read
    succeed?) before trusting `.stdout`.
    """
    if _is_root():
        return runner.run(["nft", "list", "ruleset"], read_only=True)
    return runner.run(["sudo", "-n", NFT_PATH, "list", "ruleset"], read_only=True)
