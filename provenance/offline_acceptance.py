"""Restore and verify both bundled integrations with network transports denied.

Run from a complete source checkout/distribution. Only a NEW output directory
is accepted. No reconstructed backend/agent code, model or compiler is run.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import runpy
import shutil
import subprocess
import sys


PROTOCOLS = ("file", "http", "https", "ssh", "git", "ext", "ftp", "ftps")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


class OfflineGuard:
    """Deny Python sockets and force Git transports off in reviewed setup code.

    This is an observable test boundary, not an OS firewall or a sandbox for
    malicious native executables. Only the installed Git executable may start.
    """

    def __init__(self):
        executable = shutil.which("git")
        if not executable:
            raise RuntimeError("Git is required")
        self.git = Path(executable).resolve()
        self.calls = Counter()
        self.socket_attempts = 0
        self.active = False

    def __enter__(self):
        self.original_popen = subprocess.Popen
        self.active = True
        sys.addaudithook(self._audit)
        subprocess.Popen = self._popen
        return self

    def __exit__(self, *args):
        subprocess.Popen = self.original_popen
        self.active = False

    def _audit(self, event, _arguments):
        if self.active and event.startswith("socket."):
            self.socket_attempts += 1
            raise PermissionError("Python networking denied by offline acceptance")

    def _popen(self, command, *args, **kwargs):
        if (not isinstance(command, (list, tuple)) or not command or kwargs.get("shell")
                or Path(command[0]).resolve() != self.git):
            raise PermissionError("Only the installed Git executable is permitted")
        # A later command-line setting must not override the injected denial.
        for argument in command[1:]:
            text = str(argument).lower()
            if text.startswith("protocol.") and not text.endswith("=never"):
                raise PermissionError("Git transport override denied")
            if text.startswith("--config-env"):
                raise PermissionError("Git environment configuration override denied")
        options = ["-c", "protocol.allow=never"]
        for protocol in PROTOCOLS:
            options.extend(("-c", f"protocol.{protocol}.allow=never"))
        name = "options"
        index = 1
        while index < len(command):
            part = str(command[index])
            if part in ("-c", "-C", "--git-dir", "--work-tree"):
                index += 2
            elif part == "--version":
                name = "version"
                break
            elif not part.startswith("-"):
                name = part
                break
            else:
                index += 1
        self.calls[name] += 1
        return self.original_popen([command[0], *options, *command[1:]], *args, **kwargs)

    def command(self, folder, *arguments):
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT="0", LANG="C", LC_ALL="C")
        return subprocess.run([str(self.git), "-C", str(folder), *arguments], env=env,
                              text=True, encoding="utf-8", capture_output=True, timeout=600)

    def positive_control(self, folder):
        result = self.command(folder, "ls-remote", "https://example.invalid/offline-control")
        require(result.returncode != 0 and "transport 'https' not allowed" in result.stderr,
                "Git transport-denial positive control failed")
        return {"passed": True, "exit_code": result.returncode,
                "reason": "https_transport_disabled_before_network"}


def _relative(value):
    path = PurePosixPath(value)
    require(value and not path.is_absolute() and ".." not in path.parts
            and "\\" not in value and ":" not in value, "Invalid source inventory path")
    return value


def _baseline(folder, descriptor):
    archive = descriptor["archive"]
    inventory = descriptor["inventory"]
    for item in (archive, inventory):
        path = folder / _relative(item["file"])
        require(path.resolve().is_relative_to(folder.resolve()) and not path.is_symlink(),
                "Source input escaped its integration directory")
        require(digest(path) == item["sha256"], "Source input checksum mismatch")
        if "bytes" in item:
            require(path.stat().st_size == item["bytes"], "Source input size mismatch")
    manifest = json.loads((folder / inventory["file"]).read_text(encoding="utf-8"))
    require(not manifest.get("omitted_paths"), "A source snapshot omits tracked paths")
    return manifest


def _check_tree(guard, destination, expected_tree, expected_files):
    tree = guard.command(destination, "write-tree")
    require(tree.returncode == 0 and tree.stdout.strip() == expected_tree, "Full source tree identity differs")
    paths = guard.command(destination, "ls-files", "-z")
    require(paths.returncode == 0 and set(paths.stdout.rstrip("\0").split("\0")) == set(expected_files),
            "Full tracked source path set differs")
    for name, checksum in expected_files.items():
        path = destination / _relative(name)
        require(path.is_file() and not path.is_symlink() and digest(path) == checksum,
                "Materialized source file differs: " + name)
    return {"git_tree": expected_tree, "verified_files": len(expected_files)}


def _check_base(guard, destination, revision, tree):
    kind = guard.command(destination, "cat-file", "-t", revision)
    actual = guard.command(destination, "rev-parse", "--verify", revision + "^{tree}")
    require(kind.returncode == 0 and kind.stdout.strip() == "commit"
            and actual.returncode == 0 and actual.stdout.strip() == tree,
            "Original pinned commit or baseline tree identity differs")


def run_acceptance(output, *, repository=None):
    repository = Path(repository or Path(__file__).resolve().parents[1]).resolve()
    output = Path(output).expanduser().absolute()
    require(not os.path.lexists(output), "Output already exists; it was not modified")
    output = output.parent.resolve(strict=True) / output.name
    output.mkdir(exist_ok=False)
    report = {"schema": "adaptive-inference.offline-reconstruction.v1", "passed": False,
              "scope": "offline source restoration and complete tree/file identity checks",
              "models_run": False, "native_build_run": False,
              "environment": {"system": platform.system(), "python": platform.python_version()},
              "source_sha256": {}, "integrations": {}}
    error = None
    try:
        for relative in ("provenance/offline_acceptance.py", "provenance/reconstruct.py"):
            report["source_sha256"][relative] = digest(repository / relative)
        with OfflineGuard() as guard:
            report["guard"] = {"scope": "Python socket and Git transport denial; not an OS firewall",
                               "denied_protocols": list(PROTOCOLS), "default_protocol_policy": "never",
                               "positive_control": guard.positive_control(repository)}
            for name in ("strata", "hermes"):
                folder = repository / "integrations" / name
                lock = json.loads((folder / "source-lock.json").read_text(encoding="utf-8"))
                require(lock["schema"] == 2, "Offline source lock schema 2 is required")
                baseline = _baseline(folder, lock["baseline"])
                require(baseline["revision"] == lock["base_revision"], "Baseline revision differs")
                for relative in ("setup.py", "source-lock.json"):
                    report["source_sha256"][f"integrations/{name}/{relative}"] = digest(folder / relative)
                destination = output / name
                previous_argv, previous_path = sys.argv, sys.path[:]
                previous_module = sys.modules.pop("reconstruct", None)
                try:
                    sys.argv = [str(folder / "setup.py"), "--output", str(destination)]
                    with (output / (name + ".log")).open("w", encoding="utf-8") as log:
                        with redirect_stdout(log), redirect_stderr(log):
                            runpy.run_path(str(folder / "setup.py"), run_name="__main__")
                finally:
                    sys.argv, sys.path = previous_argv, previous_path
                    sys.modules.pop("reconstruct", None)
                    if previous_module is not None:
                        sys.modules["reconstruct"] = previous_module
                receipt = json.loads((destination / ".git/adaptive-integration.json").read_text(encoding="utf-8"))
                require(receipt["offline"] is True and receipt["base_revision"] == lock["base_revision"],
                        "Reconstruction receipt is not the expected offline revision")
                require(receipt["source_lock_sha256"] == digest(folder / "source-lock.json")
                        and receipt["base_tree"] == baseline["tree"], "Reconstruction input identity differs")
                _check_base(guard, destination, lock["base_revision"], baseline["tree"])
                expected = {entry["path"]: entry["sha256"] for entry in baseline["entries"]}
                expected.update(lock["expected_files"])
                result = _check_tree(guard, destination, lock["expected_tree"], expected)
                require(receipt["reconstructed_git_tree"] == result["git_tree"], "Receipt tree differs")
                result.update(base_revision=lock["base_revision"], base_tree=baseline["tree"],
                    baseline_archive_sha256=lock["baseline"]["archive"]["sha256"],
                    baseline_inventory_sha256=lock["baseline"]["inventory"]["sha256"],
                    source_lock_sha256=digest(folder / "source-lock.json"), patches=lock["patches"], dependencies=[])
                for dependency in lock.get("dependencies", []):
                    inventory = _baseline(folder, dependency["baseline"])
                    require(inventory["revision"] == dependency["base_revision"], "Dependency revision differs")
                    dep_path = destination / _relative(dependency["output_directory"])
                    _check_base(guard, dep_path, dependency["base_revision"], inventory["tree"])
                    dep_result = _check_tree(guard, dep_path, inventory["tree"],
                        {entry["path"]: entry["sha256"] for entry in inventory["entries"]})
                    dep_result.update(name=dependency["name"], base_revision=dependency["base_revision"],
                        archive_sha256=dependency["baseline"]["archive"]["sha256"],
                        inventory_sha256=dependency["baseline"]["inventory"]["sha256"])
                    result["dependencies"].append(dep_result)
                report["integrations"][name] = result
            report["guard"]["git_command_counts"] = dict(sorted(guard.calls.items()))
            report["guard"]["python_socket_attempts"] = guard.socket_attempts
            require(guard.socket_attempts == 0, "Restoration attempted Python networking")
        report["passed"] = True
    except BaseException as exc:
        error = exc
        message = str(exc).replace(str(output), "<output>").replace(str(repository), "<source>")
        report["error"] = {"type": type(exc).__name__, "message": message[:1000]}
    finally:
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if error is not None:
        raise RuntimeError("Offline reconstruction failed; inspect result.json and local logs in the new output") from error
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New proof directory; parent must already exist")
    args = parser.parse_args()
    print(json.dumps(run_acceptance(args.output), indent=2))


if __name__ == "__main__":
    main()
