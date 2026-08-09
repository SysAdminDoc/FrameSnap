"""Release manifests and explicitly requested update discovery for FrameSnap."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


RELEASE_MANIFEST_SCHEMA_VERSION = 1
RELEASE_APPLICATION = "FrameSnap"
RELEASE_HASH_ALGORITHM = "SHA-256"
DEFAULT_UPDATE_MANIFEST_URL = (
    "https://github.com/SysAdminDoc/FrameSnap/releases/latest/download/"
    "FrameSnap-release.json"
)
MAX_RELEASE_MANIFEST_BYTES = 2 * 1024 * 1024
RELEASE_READ_CHUNK_BYTES = 64 * 1024
VERSION_PATTERN = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_RELEASE_INPUTS = (
    "framesnap.py",
    "framesnap_version.py",
    "framesnap_plugins.py",
    "framesnap_release.py",
    "tools/release_manifest.py",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "icon.ico",
    "icon.png",
    "translations/framesnap_es.ts",
    "translations/framesnap_es.qm",
    "packaging/build-windows.ps1",
    "packaging/AppRun",
    "packaging/framesnap-launcher",
    "packaging/com.sysadmindoc.FrameSnap.512.png",
    "packaging/com.sysadmindoc.FrameSnap.desktop",
    "packaging/com.sysadmindoc.FrameSnap.metainfo.xml",
    "packaging/com.sysadmindoc.FrameSnap.yml",
    "packaging/requirements-win-py312.txt",
)

VERSION_METADATA_CHECKS = (
    ("framesnap_version.py", "__version__ = \"{version}\""),
    ("README.md", "version-{version}-"),
    ("CHANGELOG.md", "## [v{version}]"),
    ("packaging/com.sysadmindoc.FrameSnap.metainfo.xml", '<release version="{version}"'),
)


class ReleaseError(ValueError):
    """Raised when a release manifest or update endpoint is invalid."""


class ReleaseVerificationError(ReleaseError):
    """Raised when a release artifact or source input does not match its manifest."""


class UpdateCheckCancelled(ReleaseError):
    """Raised when the user cancels an in-flight update check."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: str, label: str) -> Path:
    text = str(value).strip()
    path = Path(text)
    if (
        not text
        or path.is_absolute()
        or "\\" in text
        or ":" in text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReleaseError(f"{label} must be a safe relative POSIX path")
    return path


def _relative_path(root: Path, path: Path, label: str) -> str:
    resolved_root = root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ReleaseError(f"{label} must be inside {resolved_root}") from exc
    return _safe_relative_path(relative.as_posix(), label).as_posix()


def _safe_join(root: Path, relative: str, label: str) -> Path:
    path = _safe_relative_path(relative, label)
    resolved_root = root.expanduser().resolve()
    resolved_path = (resolved_root / path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ReleaseError(f"{label} escapes its root") from exc
    return resolved_path


def release_version(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise ReleaseError(f"Unsupported release version: {value!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def is_newer_release(candidate: str, current: str) -> bool:
    return release_version(candidate) > release_version(current)


def _read_project_version(source_root: Path) -> str:
    path = source_root / "framesnap_version.py"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseError(f"Could not read {path}: {exc}") from exc
    match = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    if not match:
        raise ReleaseError(f"Could not find __version__ in {path}")
    version = match.group(1)
    release_version(version)
    return version


def _version_metadata(source_root: Path, version: str) -> list[dict[str, str]]:
    metadata: list[dict[str, str]] = []
    for relative, evidence_template in VERSION_METADATA_CHECKS:
        path = source_root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReleaseError(f"Could not read version metadata {path}: {exc}") from exc
        evidence = evidence_template.format(version=version)
        if evidence not in text:
            raise ReleaseError(f"Version metadata is not synchronized in {relative}")
        metadata.append({
            "path": relative,
            "version": version,
            "sha256": sha256_file(path),
        })
    return metadata


def _git_source_state(source_root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip())
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", False


def infer_artifact_platform(path: str | Path) -> tuple[str, str]:
    name = Path(path).name
    lowered = name.casefold()
    if lowered.endswith(".exe"):
        return "windows-x64", "exe"
    if lowered.endswith(".appimage"):
        return "linux-x64", "appimage"
    if lowered.endswith(".flatpak"):
        return "linux-flatpak", "flatpak"
    return "unknown", Path(name).suffix.casefold().lstrip(".") or "file"


def build_release_manifest(
    manifest_path: str | Path,
    artifact_paths: list[str | Path],
    source_root: str | Path = ".",
    input_paths: list[str | Path] | None = None,
    base_url: str = "",
    release_url: str = "",
    source_revision: str | None = None,
    allow_dirty: bool = False,
) -> dict:
    """Build a deterministic manifest for co-located release artifacts."""
    if not artifact_paths:
        raise ReleaseError("At least one release artifact is required")
    source_root_path = Path(source_root).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    release_root = manifest_target.parent
    version = _read_project_version(source_root_path)
    version_metadata = _version_metadata(source_root_path, version)
    revision, dirty = _git_source_state(source_root_path)
    if source_revision:
        revision = str(source_revision).strip()
    if dirty and not allow_dirty:
        raise ReleaseError(
            "Source tree is dirty; commit the release inputs or pass --allow-dirty"
        )
    if base_url:
        _validate_update_url(base_url, "artifact base URL")
    if release_url:
        _validate_update_url(release_url, "release URL")

    raw_inputs = input_paths or list(DEFAULT_RELEASE_INPUTS)
    inputs: list[dict[str, str]] = []
    seen_inputs: set[str] = set()
    for raw_path in raw_inputs:
        path = _safe_join(source_root_path, str(raw_path), "source input")
        if not path.is_file():
            raise ReleaseError(f"Source input does not exist: {raw_path}")
        relative = _relative_path(source_root_path, path, "source input")
        if relative in seen_inputs:
            continue
        seen_inputs.add(relative)
        inputs.append({"path": relative, "sha256": sha256_file(path)})
    inputs.sort(key=lambda item: item["path"])

    artifacts: list[dict[str, object]] = []
    seen_artifacts: set[str] = set()
    for raw_path in artifact_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ReleaseError(f"Release artifact does not exist: {raw_path}")
        relative = _relative_path(release_root, path, "release artifact")
        if relative in seen_artifacts:
            raise ReleaseError(f"Duplicate release artifact: {relative}")
        seen_artifacts.add(relative)
        platform_name, file_format = infer_artifact_platform(path)
        artifact: dict[str, object] = {
            "name": path.name,
            "path": relative,
            "platform": platform_name,
            "format": file_format,
            "version": version,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if base_url:
            artifact["url"] = f"{base_url.rstrip('/')}/{quote(path.name)}"
        artifacts.append(artifact)
    artifacts.sort(key=lambda item: str(item["path"]))

    manifest: dict[str, object] = {
        "manifest_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "application": RELEASE_APPLICATION,
        "version": version,
        "verification": {
            "algorithm": RELEASE_HASH_ALGORITHM,
            "offline": True,
            "signing": "none",
        },
        "source": {
            "revision": revision,
            "dirty": dirty,
            "inputs": inputs,
        },
        "version_metadata": version_metadata,
        "artifacts": artifacts,
    }
    if release_url:
        manifest["release_url"] = release_url
    return manifest


def write_release_manifest(path: str | Path, manifest: dict) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_https_url(value: str, label: str) -> str:
    text = str(value).strip()
    parsed = urlsplit(text)
    if parsed.scheme.casefold() != "https" or not parsed.netloc:
        raise ReleaseError(f"{label} must be an HTTPS URL")
    return text


def _validate_update_url(value: str, label: str = "update manifest URL") -> str:
    return _validate_https_url(value, label)


def _validate_manifest_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ReleaseError("Release manifest must be a JSON object")
    if payload.get("manifest_version") != RELEASE_MANIFEST_SCHEMA_VERSION:
        raise ReleaseError("Unsupported release manifest version")
    if payload.get("application") != RELEASE_APPLICATION:
        raise ReleaseError("Release manifest application does not match FrameSnap")
    version = payload.get("version")
    release_version(str(version))
    verification = payload.get("verification")
    if not isinstance(verification, dict):
        raise ReleaseError("Release manifest verification metadata is missing")
    if verification.get("algorithm") != RELEASE_HASH_ALGORITHM:
        raise ReleaseError("Release manifest must use SHA-256 verification")
    if verification.get("offline") is not True:
        raise ReleaseError("Release manifest must support offline verification")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseError("Release manifest must contain artifacts")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ReleaseError("Release artifact entries must be JSON objects")
        name = str(artifact.get("name", "")).strip()
        if not name or Path(name).name != name or "\\" in name:
            raise ReleaseError("Release artifact names must be plain file names")
        _safe_relative_path(str(artifact.get("path", "")), "release artifact path")
        if artifact.get("version") != version:
            raise ReleaseError(f"Release artifact {name} has mismatched version metadata")
        size = artifact.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ReleaseError(f"Release artifact {name} has an invalid size")
        digest = str(artifact.get("sha256", ""))
        if not HASH_PATTERN.fullmatch(digest):
            raise ReleaseError(f"Release artifact {name} has an invalid SHA-256")
        if artifact.get("url"):
            _validate_https_url(str(artifact["url"]), f"artifact URL for {name}")
    if payload.get("release_url"):
        _validate_https_url(str(payload["release_url"]), "release URL")
    return payload


def load_release_manifest(path: str | Path) -> dict:
    manifest_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"Could not read release manifest {manifest_path}: {exc}") from exc
    return _validate_manifest_payload(payload)


def verify_release_manifest(
    manifest_path: str | Path,
    source_root: str | Path | None = None,
    check_source: bool = False,
) -> dict[str, object]:
    """Verify co-located artifacts, optionally checking source input hashes too."""
    manifest_target = Path(manifest_path).expanduser().resolve()
    manifest = load_release_manifest(manifest_target)
    release_root = manifest_target.parent
    failures: list[str] = []
    for artifact in manifest["artifacts"]:
        artifact_path = _safe_join(release_root, str(artifact["path"]), "release artifact path")
        name = str(artifact["name"])
        if not artifact_path.is_file():
            failures.append(f"{name}: missing")
            continue
        actual_size = artifact_path.stat().st_size
        if actual_size != artifact["size"]:
            failures.append(f"{name}: size mismatch")
            continue
        if sha256_file(artifact_path) != artifact["sha256"]:
            failures.append(f"{name}: SHA-256 mismatch")

    source_checked = False
    if check_source:
        source_root_path = Path(source_root or release_root).expanduser().resolve()
        for item in manifest.get("source", {}).get("inputs", []):
            input_path = _safe_join(source_root_path, str(item["path"]), "source input path")
            if not input_path.is_file():
                failures.append(f"source input {item['path']}: missing")
            elif sha256_file(input_path) != item["sha256"]:
                failures.append(f"source input {item['path']}: SHA-256 mismatch")
        for item in manifest.get("version_metadata", []):
            metadata_path = _safe_join(source_root_path, str(item["path"]), "version metadata path")
            if not metadata_path.is_file():
                failures.append(f"version metadata {item['path']}: missing")
            elif sha256_file(metadata_path) != item["sha256"]:
                failures.append(f"version metadata {item['path']}: SHA-256 mismatch")
        source_checked = True
    if failures:
        raise ReleaseVerificationError("; ".join(failures))
    return {
        "manifest": str(manifest_target),
        "application": manifest["application"],
        "version": manifest["version"],
        "artifacts": len(manifest["artifacts"]),
        "source_checked": source_checked,
    }


def _cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _read_response(response, cancel_event: threading.Event | None) -> bytes:
    body = bytearray()
    try:
        while True:
            if _cancelled(cancel_event):
                raise UpdateCheckCancelled("Update check cancelled")
            chunk = response.read(RELEASE_READ_CHUNK_BYTES)
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_RELEASE_MANIFEST_BYTES:
                raise ReleaseError("Update manifest exceeds the offline safety limit")
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    return bytes(body)


def fetch_release_manifest(
    url: str,
    cancel_event: threading.Event | None = None,
    timeout: float = 5.0,
    opener=None,
    user_agent: str = "FrameSnap",
) -> dict:
    """Fetch only release metadata over HTTPS; no media path is sent."""
    endpoint = _validate_update_url(url)
    if _cancelled(cancel_event):
        raise UpdateCheckCancelled("Update check cancelled")
    request = Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "User-Agent": str(user_agent),
        },
    )
    open_url = opener or urlopen
    try:
        response = open_url(request, timeout=timeout)
        body = _read_response(response, cancel_event)
    except UpdateCheckCancelled:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise ReleaseError(f"Update manifest request failed: {exc}") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"Update manifest is not valid UTF-8 JSON: {exc}") from exc
    return _validate_manifest_payload(payload)


@dataclass(frozen=True)
class UpdateCheck:
    current_version: str
    manifest: dict

    @property
    def available(self) -> bool:
        return is_newer_release(str(self.manifest["version"]), self.current_version)


def check_for_update(
    url: str,
    current_version: str,
    cancel_event: threading.Event | None = None,
    timeout: float = 5.0,
    opener=None,
) -> UpdateCheck:
    release_version(current_version)
    manifest = fetch_release_manifest(
        url,
        cancel_event=cancel_event,
        timeout=timeout,
        opener=opener,
        user_agent=f"FrameSnap/{current_version}",
    )
    if _cancelled(cancel_event):
        raise UpdateCheckCancelled("Update check cancelled")
    return UpdateCheck(current_version=current_version, manifest=manifest)
