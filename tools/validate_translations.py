#!/usr/bin/env python3
"""Validate Qt Linguist catalogs against literal FrameSnap translation calls."""

from __future__ import annotations

import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILE = ROOT / "framesnap.py"
TRANSLATION_DIR = ROOT / "translations"
PLACEHOLDER_RE = re.compile(r"%(?:\d+|n)|\{[^{}]+\}")


def source_strings() -> set[str]:
    tree = ast.parse(SOURCE_FILE.read_text(encoding="utf-8"), str(SOURCE_FILE))
    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = (
            node.func.attr if isinstance(node.func, ast.Attribute)
            else node.func.id if isinstance(node.func, ast.Name) else ""
        )
        if function not in {"_tr", "_trn", "_make_act"}:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            values.add(first.value)
    return values


def _translation_text(message: ET.Element) -> list[str]:
    translation = message.find("translation")
    if translation is None:
        return []
    forms = translation.findall("numerusform")
    if forms:
        return [form.text or "" for form in forms]
    return [translation.text or ""]


def catalog_strings(path: Path) -> tuple[set[str], list[str]]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return set(), [f"{path.name}: invalid XML: {exc}"]
    values: set[str] = set()
    errors: list[str] = []
    for message in root.findall("./context/message"):
        source = message.findtext("source")
        if not source:
            errors.append(f"{path.name}: message has no source")
            continue
        if source in values:
            errors.append(f"{path.name}: duplicate source: {source}")
        values.add(source)
        translations = _translation_text(message)
        if not translations or any(not text.strip() for text in translations):
            errors.append(f"{path.name}: unfinished translation: {source}")
            continue
        source_placeholders = sorted(PLACEHOLDER_RE.findall(source))
        for translated in translations:
            if sorted(PLACEHOLDER_RE.findall(translated)) != source_placeholders:
                errors.append(
                    f"{path.name}: placeholder mismatch: {source!r} -> {translated!r}"
                )
    return values, errors


def main() -> int:
    expected = source_strings()
    catalogs = sorted(TRANSLATION_DIR.glob("*.ts"))
    if not catalogs:
        print("No Qt Linguist catalogs found", file=sys.stderr)
        return 1
    failures: list[str] = []
    for catalog in catalogs:
        actual, errors = catalog_strings(catalog)
        failures.extend(errors)
        for missing in sorted(expected - actual):
            failures.append(f"{catalog.name}: missing source: {missing}")
        for stale in sorted(actual - expected):
            failures.append(f"{catalog.name}: stale source: {stale}")
        qm = catalog.with_suffix(".qm")
        if not qm.is_file() or qm.stat().st_size == 0:
            failures.append(f"{catalog.name}: missing compiled catalog {qm.name}")
    if failures:
        print("Translation validation failed:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"Validated {len(catalogs)} Qt Linguist catalog(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
