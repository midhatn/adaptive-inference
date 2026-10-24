"""Verify archived source bytes offline without importing or executing them."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


HERE = Path(__file__).resolve().parent
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def verify(root: Path = HERE) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not manifest.get("files"):
        raise ValueError("Unsupported or empty reference manifest")
    entries = manifest["files"]
    expected: dict[str, dict] = {}
    total = 0
    for entry in entries:
        name = entry["path"]
        relative = PurePosixPath(name)
        if (not isinstance(name, str) or relative.is_absolute()
                or "\\" in name or ":" in name
                or any(part in ("", ".", "..") for part in name.split("/"))
                or name in expected):
            raise ValueError("Invalid or duplicate archive path: " + str(name))
        if (not _HEX40.fullmatch(entry["source_revision"])
                or not _HEX40.fullmatch(entry["git_blob_sha1"])
                or not _HEX64.fullmatch(entry["sha256"])):
            raise ValueError("Malformed source identifier: " + name)
        target = root.joinpath(*relative.parts)
        if (not target.is_file() or target.is_symlink()
                or any(parent.is_symlink() for parent in target.parents if parent != root and root in parent.parents)
                or not target.resolve().is_relative_to(root)):
            raise ValueError("Missing, linked or out-of-tree archived file: " + name)
        data = target.read_bytes()
        if len(data) != entry["bytes"]:
            raise ValueError("Byte count mismatch: " + name)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("SHA-256 mismatch: " + name)
        git_object = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
        if hashlib.sha1(git_object).hexdigest() != entry["git_blob_sha1"]:
            raise ValueError("Git blob mismatch: " + name)
        expected_url = (
            f'https://github.com/{entry["source_repository"]}/blob/'
            f'{entry["source_revision"]}/{entry["source_path"]}'
        )
        if entry["source_url"] != expected_url or entry["modifications"] != "none":
            raise ValueError("Inconsistent source metadata: " + name)
        expected[name] = entry
        total += len(data)
    for name, entry in expected.items():
        license_entry = expected.get(entry["license_path"])
        if (not license_entry or license_entry["kind"] != "license"
                or license_entry["source_repository"] != entry["source_repository"]
                or license_entry["source_revision"] != entry["source_revision"]
                or license_entry["license_spdx"] != entry["license_spdx"]):
            raise ValueError("Missing or inconsistent license reference: " + name)
    grouped: set[str] = set()
    for group in manifest["groups"]:
        prefix = group["archive_prefix"] + "/"
        matched = [name for name in expected if name.startswith(prefix)]
        if not matched:
            raise ValueError("Empty source group: " + prefix)
        for name in matched:
            entry = expected[name]
            if (entry["source_repository"] != group["repository"]
                    or entry["source_revision"] != group["revision"]
                    or entry["license_spdx"] != group["license"]
                    or name in grouped):
                raise ValueError("Inconsistent source group: " + name)
            grouped.add(name)
        for target in (root / group["archive_prefix"]).rglob("*"):
            if target.is_symlink():
                raise ValueError("Linked archive entry: " + str(target))
            if target.is_file() and target.relative_to(root).as_posix() not in expected:
                raise ValueError("Unlisted archived file: " + str(target))
    if grouped != set(expected):
        raise ValueError("Ungrouped source files")
    return {
        "passed": True,
        "files_verified": len(expected),
        "groups_verified": len(manifest["groups"]),
        "bytes_verified": total,
        "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
        "scope": "Offline byte integrity and license-reference consistency; no upstream authentication or code execution",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE, help="Reference archive directory")
    args = parser.parse_args()
    print(json.dumps(verify(args.root), indent=2))


if __name__ == "__main__":
    main()
