"""Opt-in, local extension points for FrameSnap analysis and export services.

Discovery only reads JSON manifests. Python extension code runs only after an
explicit ``load`` or ``load_opt_in`` call; session and template readers never
call this module.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Protocol


PLUGIN_API_VERSION = 1
PLUGIN_MANIFEST_VERSION = 1
PLUGIN_MANIFEST_NAME = "plugin.json"
PLUGIN_CAPABILITIES = frozenset({"detector", "probe", "exporter"})
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
EXTENSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")


class PluginError(ValueError):
    """Raised when a plugin manifest or explicit load request is unsafe."""


class Detector(Protocol):
    def __call__(self, frame: Any) -> Any:
        ...


class Probe(Protocol):
    def __call__(self, source_path: str) -> Mapping[str, Any]:
        ...


class Exporter(Protocol):
    def __call__(self, request: Any, output_path: str) -> Any:
        ...


@dataclass(frozen=True)
class PluginManifest:
    """Validated, non-executable metadata for one local extension."""

    plugin_id: str
    name: str
    version: str
    api_version: int
    entrypoint: str
    capabilities: tuple[str, ...]
    manifest_path: Path
    enabled: bool = False

    @classmethod
    def from_file(cls, path: str | Path) -> "PluginManifest":
        manifest_path = Path(path).expanduser().resolve()
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"Could not read plugin manifest {manifest_path.name}: {exc}") from exc
        if not isinstance(payload, dict):
            raise PluginError("Plugin manifest must be a JSON object")
        try:
            manifest_version = int(payload.get("manifest_version", 0))
            api_version = int(payload.get("api_version", 0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise PluginError("Plugin manifest versions must be integers") from exc
        if manifest_version != PLUGIN_MANIFEST_VERSION:
            raise PluginError(
                f"Unsupported plugin manifest version {manifest_version}; "
                f"expected {PLUGIN_MANIFEST_VERSION}"
            )
        if api_version != PLUGIN_API_VERSION:
            raise PluginError(
                f"Plugin API version {api_version} is incompatible with "
                f"FrameSnap API {PLUGIN_API_VERSION}"
            )
        plugin_id = str(payload.get("id", "")).strip().casefold()
        name = str(payload.get("name", "")).strip()
        version = str(payload.get("version", "")).strip()
        entrypoint = str(payload.get("entrypoint", "")).strip()
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError("Plugin id must use lowercase letters, digits, '.', '_' or '-'")
        if not name or not EXTENSION_NAME_PATTERN.fullmatch(name):
            raise PluginError("Plugin name is missing or contains unsupported characters")
        if not version or len(version) > 32:
            raise PluginError("Plugin version is missing or too long")
        module_name, separator, function_name = entrypoint.partition(":")
        if (
            not separator or not function_name or Path(module_name).suffix.casefold() != ".py"
            or Path(module_name).name != module_name
            or any(part in module_name for part in ("..", "\\", "/"))
        ):
            raise PluginError("Plugin entrypoint must be a local Python file and function")
        raw_capabilities = payload.get("capabilities", [])
        if not isinstance(raw_capabilities, list) or not raw_capabilities:
            raise PluginError("Plugin must declare at least one capability")
        capabilities = tuple(sorted({str(value).strip().casefold() for value in raw_capabilities}))
        if any(value not in PLUGIN_CAPABILITIES for value in capabilities):
            raise PluginError("Plugin declares an unsupported capability")
        return cls(
            plugin_id=plugin_id,
            name=name,
            version=version,
            api_version=api_version,
            entrypoint=entrypoint,
            capabilities=capabilities,
            manifest_path=manifest_path,
            enabled=bool(payload.get("enabled", False)),
        )

    @property
    def plugin_root(self) -> Path:
        return self.manifest_path.parent

    @property
    def module_path(self) -> Path:
        return self.plugin_root / self.entrypoint.split(":", 1)[0]

    @property
    def register_function(self) -> str:
        return self.entrypoint.split(":", 1)[1]

    def descriptor(self, root: str | Path | None = None) -> dict[str, Any]:
        manifest_path = self.manifest_path
        if root is not None:
            try:
                manifest_path = manifest_path.relative_to(Path(root).expanduser().resolve())
            except ValueError:
                pass
        return {
            "id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "entrypoint": self.entrypoint,
            "capabilities": list(self.capabilities),
            "enabled": self.enabled,
            "manifest": str(manifest_path),
        }


@dataclass(frozen=True)
class ExtensionDescriptor:
    kind: str
    name: str
    plugin_id: str
    description: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "plugin_id": self.plugin_id,
            "description": self.description,
        }


def _safe_plugin_child(root: Path, candidate: Path) -> Path:
    root = root.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    try:
        common = os.path.commonpath((str(root), str(resolved)))
    except ValueError as exc:
        raise PluginError("Plugin path is on a different filesystem root") from exc
    if os.path.normcase(common) != os.path.normcase(str(root)):
        raise PluginError("Plugin path escapes the selected plugin directory")
    if candidate.is_symlink() or resolved.is_symlink():
        raise PluginError("Plugin symlinks are not allowed")
    return resolved


class PluginRegistry:
    """Versioned registry for explicitly enabled local plugin services."""

    def __init__(self, api_version: int = PLUGIN_API_VERSION):
        if api_version != PLUGIN_API_VERSION:
            raise PluginError(f"Unsupported registry API version: {api_version}")
        self.api_version = api_version
        self._manifests: dict[str, PluginManifest] = {}
        self._loaded: set[str] = set()
        self._modules: dict[str, ModuleType] = {}
        self._extensions: dict[str, dict[str, tuple[ExtensionDescriptor, Callable]]] = {
            "detector": {}, "probe": {}, "exporter": {},
        }
        self._active_plugin: PluginManifest | None = None
        self._errors: list[str] = []

    def discover(self, directory: str | Path) -> list[PluginManifest]:
        """Read manifests without importing or executing any plugin code."""
        root = Path(directory).expanduser().resolve()
        if not root.exists():
            return []
        if not root.is_dir() or root.is_symlink():
            raise PluginError("Plugin directory must be a real directory")
        candidates = []
        direct_manifest = root / PLUGIN_MANIFEST_NAME
        if direct_manifest.is_file():
            candidates.append(direct_manifest)
        candidates.extend(
            path / PLUGIN_MANIFEST_NAME
            for path in sorted(root.iterdir(), key=lambda item: item.name.casefold())
            if path.is_dir() and not path.is_symlink()
            and (path / PLUGIN_MANIFEST_NAME).is_file()
        )
        manifests = []
        for candidate in candidates:
            manifest_path = _safe_plugin_child(root, candidate)
            manifest = PluginManifest.from_file(manifest_path)
            if manifest.plugin_id in self._manifests:
                raise PluginError(f"Duplicate plugin id: {manifest.plugin_id}")
            self._manifests[manifest.plugin_id] = manifest
            manifests.append(manifest)
        return manifests

    def manifests(self) -> list[PluginManifest]:
        return [self._manifests[key] for key in sorted(self._manifests)]

    def _validate_extension(self, kind: str, name: str, callback: Callable,
                            description: str) -> tuple[ExtensionDescriptor, Callable]:
        if kind not in self._extensions:
            raise PluginError(f"Unknown extension kind: {kind}")
        if not callable(callback):
            raise PluginError(f"{kind} extension {name!r} is not callable")
        if not EXTENSION_NAME_PATTERN.fullmatch(name):
            raise PluginError(f"Invalid {kind} extension name: {name!r}")
        plugin = self._active_plugin
        if plugin is None:
            raise PluginError("Extensions can only be registered while a plugin is loading")
        if kind not in plugin.capabilities:
            raise PluginError(f"Plugin {plugin.plugin_id} did not declare {kind} capability")
        if name in self._extensions[kind]:
            raise PluginError(f"Duplicate {kind} extension: {name}")
        return ExtensionDescriptor(kind, name, plugin.plugin_id, description.strip()), callback

    def _register(self, kind: str, name: str, callback: Callable,
                  description: str = "") -> None:
        descriptor, validated = self._validate_extension(
            kind, name, callback, description
        )
        self._extensions[kind][name] = (descriptor, validated)

    def register_detector(self, name: str, callback: Detector,
                          description: str = "") -> None:
        self._register("detector", name, callback, description)

    def register_probe(self, name: str, callback: Probe,
                       description: str = "") -> None:
        self._register("probe", name, callback, description)

    def register_exporter(self, name: str, callback: Exporter,
                          description: str = "") -> None:
        self._register("exporter", name, callback, description)

    def load(self, plugin_id: str) -> PluginManifest:
        """Explicitly import one discovered plugin and call its register hook."""
        plugin_id = str(plugin_id).strip().casefold()
        manifest = self._manifests.get(plugin_id)
        if manifest is None:
            raise PluginError(f"Plugin is not discovered: {plugin_id}")
        if plugin_id in self._loaded:
            return manifest
        module_path = _safe_plugin_child(manifest.plugin_root, manifest.module_path)
        if not module_path.is_file() or module_path.suffix.casefold() != ".py":
            raise PluginError(f"Plugin entrypoint is missing: {manifest.entrypoint}")
        module_name = f"framesnap_plugin_{manifest.plugin_id.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise PluginError(f"Could not load plugin entrypoint: {manifest.entrypoint}")
        module = importlib.util.module_from_spec(spec)
        before = {
            kind: set(entries) for kind, entries in self._extensions.items()
        }
        self._active_plugin = manifest
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            register = getattr(module, manifest.register_function, None)
            if not callable(register):
                raise PluginError(f"Plugin register function is missing: {manifest.register_function}")
            register(self)
        except PluginError:
            for kind, entries in self._extensions.items():
                for name in set(entries) - before[kind]:
                    if entries[name][0].plugin_id == plugin_id:
                        del entries[name]
            sys.modules.pop(module_name, None)
            raise
        except Exception as exc:
            for kind, entries in self._extensions.items():
                for name in set(entries) - before[kind]:
                    if entries[name][0].plugin_id == plugin_id:
                        del entries[name]
            sys.modules.pop(module_name, None)
            raise PluginError(f"Plugin {plugin_id} failed while loading: {exc}") from exc
        finally:
            self._active_plugin = None
        self._modules[plugin_id] = module
        self._loaded.add(plugin_id)
        return manifest

    def load_opt_in(self, directory: str | Path,
                    enabled_ids: list[str] | tuple[str, ...] | set[str] | None = None
                    ) -> list[PluginManifest]:
        """Discover manifests and load only explicitly enabled ids."""
        manifests = self.discover(directory)
        allowed = (
            {str(value).strip().casefold() for value in enabled_ids}
            if enabled_ids is not None
            else {manifest.plugin_id for manifest in manifests if manifest.enabled}
        )
        loaded = []
        for manifest in manifests:
            if manifest.plugin_id in allowed:
                loaded.append(self.load(manifest.plugin_id))
        return loaded

    def get(self, kind: str, name: str) -> Callable:
        try:
            return self._extensions[kind][name][1]
        except KeyError as exc:
            raise PluginError(f"Unknown {kind} extension: {name}") from exc

    def describe(self, root: str | Path | None = None) -> dict[str, Any]:
        """Return stable metadata without exposing callbacks or executing code."""
        return {
            "api_version": self.api_version,
            "manifest_version": PLUGIN_MANIFEST_VERSION,
            "plugins": [manifest.descriptor(root) for manifest in self.manifests()],
            "extensions": {
                kind: [
                    descriptor.as_dict()
                    for descriptor, _callback in sorted(
                        entries.values(), key=lambda pair: pair[0].name.casefold()
                    )
                ]
                for kind, entries in sorted(self._extensions.items())
            },
            "loaded": sorted(self._loaded),
            "errors": list(self._errors),
        }
