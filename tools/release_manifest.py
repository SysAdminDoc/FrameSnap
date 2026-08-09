#!/usr/bin/env python3
"""Create and verify offline FrameSnap release manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from framesnap_release import (  # noqa: E402
    ReleaseError,
    build_release_manifest,
    verify_release_manifest,
    write_release_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify a deterministic FrameSnap release manifest."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="hash release artifacts and source inputs")
    create.add_argument("--output", required=True, help="manifest path")
    create.add_argument(
        "--artifact", action="append", required=True,
        help="co-located release artifact; repeat for each artifact",
    )
    create.add_argument("--source-root", default=".")
    create.add_argument(
        "--input", dest="input_paths", action="append",
        help="source input relative to --source-root; defaults to all release inputs",
    )
    create.add_argument("--base-url", default="", help="HTTPS URL prefix for artifact downloads")
    create.add_argument("--release-url", default="", help="HTTPS URL for release notes")
    create.add_argument("--source-revision", default="", help="override the detected Git revision")
    create.add_argument(
        "--allow-dirty", action="store_true",
        help="record a dirty source tree instead of failing",
    )

    verify = commands.add_parser("verify", help="verify artifact hashes without network access")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--source-root", default="")
    verify.add_argument(
        "--check-source", action="store_true",
        help="also verify recorded source-input and version-metadata hashes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = build_release_manifest(
                args.output,
                args.artifact,
                source_root=args.source_root,
                input_paths=args.input_paths,
                base_url=args.base_url,
                release_url=args.release_url,
                source_revision=args.source_revision or None,
                allow_dirty=args.allow_dirty,
            )
            write_release_manifest(args.output, manifest)
            print(
                f"Wrote {args.output}: version {manifest['version']}, "
                f"{len(manifest['artifacts'])} artifact(s)"
            )
            return 0

        result = verify_release_manifest(
            args.manifest,
            source_root=args.source_root or None,
            check_source=args.check_source,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ReleaseError) as exc:
        print(f"Release manifest failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
