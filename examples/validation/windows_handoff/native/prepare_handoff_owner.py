"""Create a new handoff owner from an explicitly pinned existing owner package.

Copies only verified Strata source/native/tokenizer/seed files. Model assets and
Python environments remain explicit external prerequisites. No process starts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
HELPERS = ("engine.py", "ownership.py", "owned_job.py", "memory_monitor.py", "memory_reader.py")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def relocate_config(config, source, output):
    """Exact path moves and one declared lifecycle setting; quality is copied."""
    result = json.loads(json.dumps(config))
    mappings = (("cwd", "runtime/Strata"), ("exe", "runtime/native/strata.exe"),
                ("tokenizer", "runtime/tokenizer"))
    for key, relative in mappings:
        if Path(result[key]).resolve() != (source / relative).resolve():
            raise ValueError("Unexpected baseline configuration path: " + key)
        result[key] = str(output / relative)
    if result["lib_dirs"] != [str(source / "runtime/native")]:
        raise ValueError("Unexpected baseline native library directories")
    if Path(result["vision"]["exe"]).resolve() != (source / "runtime/native/strata-vision.exe").resolve():
        raise ValueError("Unexpected baseline vision executable")
    result["lib_dirs"] = [str(output / "runtime/native")]
    result["vision"]["exe"] = str(output / "runtime/native/strata-vision.exe")
    previous_idle = result.get("idle_unload_s")
    if type(previous_idle) not in (int, float) or previous_idle < 0:
        raise ValueError("Baseline idle timer must be explicit")
    result["idle_unload_s"] = 0
    return result, {"idle_unload_s": {"before": previous_idle, "after": 0},
                    "path_fields_relocated": ["cwd", "exe", "tokenizer", "lib_dirs", "vision.exe"]}


def prepare(source, output, manifest_pin, provenance_pin, owner_sources=HERE / "owner_source"):
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    owner_sources = Path(owner_sources).resolve(strict=True)
    if output.exists() or not output.parent.is_dir() or output.parent.resolve() != output.parent:
        raise ValueError("Output must be a new directory under an existing non-redirected parent")
    if digest(source / "MANIFEST.json") != manifest_pin or digest(source / "PROVENANCE.json") != provenance_pin:
        raise RuntimeError("Source manifest or provenance pin differs")
    manifest = json.loads((source / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
    provenance = json.loads((source / "PROVENANCE.json").read_text(encoding="utf-8"))
    pins = json.loads((owner_sources / "source-pins.json").read_text(encoding="utf-8"))
    selected = {name: pin for name, pin in manifest.items()
                if name.startswith(("runtime/Strata/", "runtime/native/", "runtime/tokenizer/"))
                or name == "runtime/expert-profile.seed.bin"}
    if not all(any(name.startswith(prefix) for name in selected) for prefix in
               ("runtime/Strata/", "runtime/native/", "runtime/tokenizer/")) or "runtime/expert-profile.seed.bin" not in selected:
        raise RuntimeError("Required sealed runtime/source/tokenizer/seed files are missing")
    # Admit every input before making an output directory.
    admitted = {**selected, "config/server-template.json": manifest["config/server-template.json"]}
    for name, expected in admitted.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise RuntimeError("Source manifest path is not package-relative")
        path = (source / name).resolve(strict=True)
        if not path.is_relative_to(source) or digest(path) != expected:
            raise RuntimeError("Source file is not the sealed input: " + name)
    for name in HELPERS:
        if (digest(source / name) != pins["files"][name]["original_sha256"]
                or digest(owner_sources / name) != pins["files"][name]["preserved_sha256"]):
            raise RuntimeError("Owner helper lineage differs: " + name)
    config = json.loads((source / "config/server-template.json").read_text(encoding="utf-8"))
    config, changes = relocate_config(config, source, output)
    output.mkdir()
    copied_bytes = 0
    for name, expected in selected.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
        if digest(destination) != expected:
            raise RuntimeError("Copied file differs: " + name)
        copied_bytes += destination.stat().st_size
    for name in HELPERS:
        shutil.copyfile(owner_sources / name, output / name)
        if digest(output / name) != pins["files"][name]["preserved_sha256"]:
            raise RuntimeError("Copied owner helper differs: " + name)
    (output / "config").mkdir()
    write(output / "config/server-template.json", config)
    provenance["composition_scope"] = "Separate desktop-handoff owner; unchanged qualified native/quality, host-managed idle lifecycle"
    provenance["strata"]["source"] = str(output / "runtime/Strata")
    provenance.pop("hermes", None)
    unused = provenance["dependencies"].pop("hermes_python", None)
    if unused:
        provenance["dependencies_sha256"].pop(unused, None)
        provenance["dependencies_sha256"].pop(str(Path(unused).parent.parent / "pyvenv.cfg"), None)
    provenance["handoff_profile"] = {"schema": 1, "idle_controller": "desktop_host", "idle_unload_s": 0,
        "base_manifest_sha256": manifest_pin, "base_provenance_sha256": provenance_pin,
        "quality_model_guard_changes": False}
    write(output / "PROVENANCE.json", provenance)
    receipt = {"schema": 1, "base_manifest_sha256": manifest_pin, "base_provenance_sha256": provenance_pin,
        "copied_files": len(selected), "copied_bytes": copied_bytes, "copied_file_sha256": selected,
        "owner_helpers": pins["files"], "configuration_changes": changes,
        "native_sha256": digest(output / "runtime/native/strata.exe"),
        "model_assets_copied": False, "state_or_runs_copied": False, "process_started": False,
        "scope": "New owner package; full source/native hashes retained; model metadata and interpreter prerequisites remain external"}
    write(output / "HANDOFF-PREPARATION.json", receipt)
    files = {str(path.relative_to(output)).replace("\\", "/"): digest(path)
             for path in sorted(output.rglob("*")) if path.is_file()}
    write(output / "MANIFEST.json", {"schema": "adaptive-engine-manifest.v1", "files": files})
    return {"package": str(output), "manifest_sha256": digest(output / "MANIFEST.json"),
            "provenance_sha256": digest(output / "PROVENANCE.json"), "max_runtime_seconds": 900,
            "copied_files": len(selected), "copied_bytes": copied_bytes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--source-provenance-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_package, args.output, args.source_manifest_sha256,
                             args.source_provenance_sha256), indent=2))


if __name__ == "__main__":
    main()
