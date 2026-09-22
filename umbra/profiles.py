"""Load, validate, and merge posture profiles (spec §2).

A profile is declarative YAML. Loading it means:
  1. read the YAML,
  2. resolve `extends` by deep-merging onto the parent (child wins),
  3. validate the *result* against schema/profile.schema.json,
so a typo in a security posture fails loudly instead of silently no-opping.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from umbra import paths


class ProfileError(Exception):
    """Raised for a missing, malformed, or schema-invalid profile."""


@dataclass
class Profile:
    """A validated posture. `data` is the fully-merged dict."""
    name: str
    data: dict

    @property
    def fail_mode(self) -> str:
        return self.data.get("meta", {}).get("fail_mode", "closed")

    @property
    def require_confirm(self) -> bool:
        return self.data.get("meta", {}).get("require_confirm", False)

    def module_config(self, module: str) -> dict:
        """The profile fragment for one module, e.g. module_config('netdark')."""
        return self.data.get("modules", {}).get(module, {"enabled": False})


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` onto `base`; override wins on conflicts.

    Used for `extends`: the child profile is layered on top of its parent so a
    child need only state what it changes.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_yaml(name: str, profiles_dir: Path) -> dict:
    from umbra.validate import ValidationError, safe_name
    try:
        safe_name(name, "profile name")
    except ValidationError as exc:
        raise ProfileError(str(exc)) from exc
    path = profiles_dir / f"{name}.yaml"
    if not path.exists():
        raise ProfileError(f"no such profile: {name} (looked in {profiles_dir})")
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"profile {name} is not valid YAML: {exc}") from exc


def _resolve(name: str, profiles_dir: Path, _seen: tuple[str, ...] = ()) -> dict:
    """Read a profile and fold in its `extends` chain, detecting cycles."""
    if name in _seen:
        chain = " -> ".join((*_seen, name))
        raise ProfileError(f"circular extends chain: {chain}")
    raw = _read_yaml(name, profiles_dir)
    parent_name = raw.get("extends")
    if not parent_name:
        return raw
    parent = _resolve(parent_name, profiles_dir, (*_seen, name))
    merged = _deep_merge(parent, raw)
    merged.pop("extends", None)          # fully resolved; drop the marker
    # Identity fields belong to the child, never the inherited parent.
    merged["name"] = raw.get("name", name)
    if "description" in raw:
        merged["description"] = raw["description"]
    return merged


def _validate(data: dict) -> None:
    schema = json.loads(paths.PROFILE_SCHEMA.read_text())
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        lines = [f"  - {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]
        raise ProfileError("profile failed validation:\n" + "\n".join(lines))


def load_profile(name: str, profiles_dir: Path | None = None) -> Profile:
    """Public entry point: name -> validated, fully-merged Profile."""
    profiles_dir = profiles_dir or paths.PROFILES_DIR
    data = _resolve(name, profiles_dir)
    _validate(data)
    if data.get("name") != name:
        # Guard against a file whose internal name disagrees with its filename.
        raise ProfileError(f"profile file {name}.yaml declares name={data.get('name')!r}")
    return Profile(name=name, data=data)


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    profiles_dir = profiles_dir or paths.PROFILES_DIR
    return sorted(p.stem for p in profiles_dir.glob("*.yaml"))
