"""kernel - OS/kernel hardening.

Phase-11 controls:
  * hardening_sysctls -- a set of well-established hardening sysctls (each its own
                        control so each restores independently).
  * disable_webcam    -- unload the webcam driver (uvcvideo) so no process can
                        turn the camera on.

Only cleanly-REVERSIBLE sysctls are included. Deliberately excluded:
kernel.kexec_load_disabled and kernel.unprivileged_bpf_disabled=2 are one-way
(cannot be reset until reboot), which would break umbra's clean-revert promise.
"""

from __future__ import annotations

from umbra.modules.base import Action, Compliance, Control, Module, VerifyResult

# key -> hardened value. All runtime-reversible by root.
_SYSCTLS = {
    "kernel.kptr_restrict": "2",            # hide kernel pointers from userspace
    "kernel.dmesg_restrict": "1",           # non-root can't read the kernel log
    "kernel.yama.ptrace_scope": "2",        # restrict ptrace to admin
    "fs.suid_dumpable": "0",                # no core dumps of setuid programs
    "kernel.randomize_va_space": "2",       # full ASLR
    "kernel.perf_event_paranoid": "3",      # lock down perf_event_open
    "net.ipv4.conf.all.rp_filter": "1",     # reverse-path filtering (anti-spoof)
    "net.ipv4.conf.default.rp_filter": "1",
}

_WEBCAM_MODULE = "uvcvideo"


def _cid(key: str) -> str:
    return f"kernel.sc_{key.replace('.', '_')}"


class KernelModule(Module):
    name = "kernel"

    def controls(self) -> list[Control]:
        ctrls: list[Control] = []
        if self.config.get("hardening_sysctls", False):
            for key in _SYSCTLS:
                ctrls.append(Control(_cid(key), f"sysctl {key}", "sysctl_set"))
        if self.config.get("disable_webcam", False):
            ctrls.append(Control("kernel.disable_webcam", "Unload the webcam driver", "module_load"))
        return ctrls

    # --- measure -------------------------------------------------------------

    def measure(self) -> dict[str, "ControlState"]:  # noqa: F821
        from umbra.modules.base import ControlState

        states: dict[str, ControlState] = {}
        if not self.enabled:
            return states
        if self.config.get("hardening_sysctls", False):
            for key, want in _SYSCTLS.items():
                states[_cid(key)] = self._measure_sysctl(key, want)
        if self.config.get("disable_webcam", False):
            states["kernel.disable_webcam"] = self._measure_webcam()
        return states

    def _measure_sysctl(self, key: str, want: str) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        res = self.runner.run(["sysctl", "-n", key], read_only=True)
        if not res.available:
            return ControlState(_cid(key), Compliance.UNKNOWN, detail="sysctl unavailable")
        if res.stdout.strip() == "":
            return ControlState(_cid(key), Compliance.UNSUPPORTED, detail=f"{key} not present")
        return ControlState(
            _cid(key),
            Compliance.COMPLIANT if res.stdout.strip() == want else Compliance.DRIFT,
            observed={key: res.stdout.strip()},
        )

    def _measure_webcam(self) -> "ControlState":  # noqa: F821
        from umbra.modules.base import ControlState

        res = self.runner.run(["lsmod"], read_only=True)
        if not res.available:
            return ControlState("kernel.disable_webcam", Compliance.UNKNOWN)
        loaded = any(line.split()[0] == _WEBCAM_MODULE
                     for line in res.stdout.splitlines() if line.strip())
        return ControlState(
            "kernel.disable_webcam",
            Compliance.DRIFT if loaded else Compliance.COMPLIANT,
            detail="" if loaded else "no webcam driver loaded",
        )

    # --- plan / apply --------------------------------------------------------

    def plan(self) -> list[Action]:
        if not self.enabled:
            return []
        return [
            Action(control, self.config, reason=state.detail or "drift")
            for control, state in self.measure().items()
            if state.compliance is Compliance.DRIFT
        ]

    def apply(self, action: Action, snap) -> None:
        if action.control == "kernel.disable_webcam":
            self._apply_webcam(snap)
        elif action.control.startswith("kernel.sc_"):
            self._apply_sysctl(action.control, snap)

    def _apply_sysctl(self, control: str, snap) -> None:
        key = next(k for k in _SYSCTLS if _cid(k) == control)
        prior = self.runner.run(["sysctl", "-n", key], read_only=True)
        snap.record(control, "sysctl_set", {"key": key, "value": prior.stdout.strip() or "0"})
        self.runner.run(["sysctl", "-w", f"{key}={_SYSCTLS[key]}"], read_only=False, check=True)

    def _apply_webcam(self, snap) -> None:
        snap.record("kernel.disable_webcam", "module_load",
                    {"module": _WEBCAM_MODULE, "was_loaded": True})
        self.runner.run(["modprobe", "-r", _WEBCAM_MODULE], read_only=False, check=False)

    def verify(self, action: Action) -> VerifyResult:
        state = self.measure().get(action.control)
        ok = state is not None and state.compliance is Compliance.COMPLIANT
        return VerifyResult(action.control, ok, state.detail if state else "no state")

    def restore(self, snap) -> None:
        return None
