"""The single shim every external command goes through.

Why funnel everything through one class instead of calling subprocess directly
all over the codebase?

  * dry-run   -- a state-changing command can be *shown* instead of run, so
                 `umbra plan` and `--dry-run` are honest previews.
  * logging   -- every command Umbra runs is recorded in one place.
  * safety    -- read-only probes always execute (they can't hurt you), but
                 mutations respect dry-run.
  * testing   -- one seam to fake in unit tests.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger("umbra.runner")

# A fixed, trusted PATH used for every subprocess, so a hostile PATH in the
# environment can't make umbra run an attacker's `nft`/`systemctl`/`sysctl`.
_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Default per-command timeout (seconds). No umbra command should legitimately run
# longer; a hang otherwise wedges the whole apply.
_DEFAULT_TIMEOUT = 120


@dataclass
class RunResult:
    """The outcome of one command."""
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    executed: bool          # False when skipped due to dry-run
    available: bool         # False when the binary was not found on this host

    @property
    def ok(self) -> bool:
        return self.executed and self.returncode == 0


class Runner:
    """Runs external commands, honouring dry-run for mutations.

    A single Runner is created by the CLI and threaded through the engine and
    every module, so there is exactly one dry_run flag for the whole run.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def which(self, binary: str) -> bool:
        """Is this tool installed? Modules use this to decide UNSUPPORTED."""
        return shutil.which(binary) is not None

    def _clean_env(self) -> dict[str, str]:
        """The environment for a subprocess: inherit, but force a trusted PATH and
        a stable locale, and drop IFS."""
        env = dict(os.environ)
        env["PATH"] = _SAFE_PATH
        env["LC_ALL"] = "C"
        env.pop("IFS", None)
        return env

    def run(
        self,
        argv: list[str],
        *,
        read_only: bool,
        check: bool = False,
        input_text: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Execute (or, for a mutation in dry-run, pretend to execute) a command.

        read_only=True  -> a probe with no side effects; ALWAYS runs, even in
                           dry-run, because measuring is safe and the plan needs
                           the real current state.
        read_only=False -> a mutation; skipped and only logged when dry_run.

        check=True raises RuntimeError on a non-zero exit or a timeout (use for
        steps where a failure must abort the transaction).
        """
        binary = argv[0]
        if not self.which(binary):
            # On a non-Linux dev box (or a host missing nft/systemctl) we don't
            # crash -- we report "unavailable" and let measure() map that to a
            # ControlState of UNKNOWN.
            log.debug("command unavailable: %s", binary)
            return RunResult(argv, 127, "", f"{binary}: not found", False, False)

        if not read_only and self.dry_run:
            log.info("DRY-RUN would execute: %s", " ".join(argv))
            return RunResult(argv, 0, "", "", False, True)

        log.debug("exec: %s", " ".join(argv))
        try:
            proc = subprocess.run(
                argv,
                input=input_text,
                capture_output=True,
                text=True,
                env=self._clean_env(),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            log.error("command timed out after %ss: %s", timeout, " ".join(argv))
            if check:
                raise RuntimeError(f"command timed out ({timeout}s): {' '.join(argv)}") from exc
            return RunResult(argv, 124, exc.stdout or "",
                             (exc.stderr or "") + "\n<timed out>", executed=True, available=True)

        result = RunResult(
            argv,
            proc.returncode,
            proc.stdout,
            proc.stderr,
            executed=True,
            available=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"command failed ({proc.returncode}): {' '.join(argv)}\n{proc.stderr.strip()}"
            )
        return result
