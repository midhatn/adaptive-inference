import json
from pathlib import Path
import tempfile
import unittest

from prepare_handoff_owner import HELPERS, digest, prepare, write


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source, self.helpers, self.output = (self.root / name for name in ("source", "helpers", "output"))
        self.source.mkdir(); self.helpers.mkdir()
        for name in ("runtime/Strata/server.py", "runtime/native/strata.exe", "runtime/native/strata-vision.exe",
                     "runtime/tokenizer/vocab.json", "runtime/expert-profile.seed.bin"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        pins = {}
        for name in HELPERS:
            (self.source / name).write_text("original " + name)
            (self.helpers / name).write_text("preserved " + name)
            pins[name] = {"original_sha256": digest(self.source / name),
                          "preserved_sha256": digest(self.helpers / name)}
        write(self.helpers / "source-pins.json", {"files": pins})
        (self.source / "config").mkdir()
        self.config = {"cwd": str(self.source / "runtime/Strata"),
                       "exe": str(self.source / "runtime/native/strata.exe"),
                       "tokenizer": str(self.source / "runtime/tokenizer"),
                       "lib_dirs": [str(self.source / "runtime/native")],
                       "vision": {"exe": str(self.source / "runtime/native/strata-vision.exe"),
                                  "gpu": False, "model": "external-model"},
                       "idle_unload_s": 60, "args": ["--max-context", "65536"],
                       "reasoning_effort": "high", "reasoning_budget_tokens": 8192,
                       "sampling": {"experimental_speed_projection": False}}
        write(self.source / "config/server-template.json", self.config)
        write(self.source / "PROVENANCE.json", {"strata": {"source": "old", "revision": "exact"},
              "dependencies": {"owner_python": "external-python"}, "dependencies_sha256": {},
              "asset_metadata": {"external-model": {"size": 100, "mtime_ns": 123}}})
        self.manifest = {str(p.relative_to(self.source)).replace("\\", "/"): digest(p)
                         for p in self.source.rglob("*") if p.is_file()}
        write(self.source / "MANIFEST.json", {"files": self.manifest})
        self.mp, self.pp = digest(self.source / "MANIFEST.json"), digest(self.source / "PROVENANCE.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_new_profile_changes_only_declared_idle_and_package_paths(self):
        result = prepare(self.source, self.output, self.mp, self.pp, self.helpers)
        cfg = json.loads((self.output / "config/server-template.json").read_text())
        self.assertEqual(cfg["idle_unload_s"], 0)
        for key in ("args", "sampling", "reasoning_effort", "reasoning_budget_tokens"):
            self.assertEqual(cfg[key], self.config[key])
        self.assertEqual(cfg["vision"]["gpu"], self.config["vision"]["gpu"])
        self.assertEqual(cfg["vision"]["model"], "external-model")
        self.assertEqual(result["manifest_sha256"], digest(self.output / "MANIFEST.json"))
        self.assertFalse((self.output / "runs").exists())
        self.assertFalse((self.output / "state").exists())
        self.assertEqual(digest(self.source / "MANIFEST.json"), self.mp)
        self.assertEqual(digest(self.output / "runtime/native/strata.exe"), self.manifest["runtime/native/strata.exe"])
        provenance = json.loads((self.output / "PROVENANCE.json").read_text())
        self.assertEqual(provenance["asset_metadata"], {"external-model": {"size": 100, "mtime_ns": 123}})

    def test_existing_output_is_read_only_refusal(self):
        self.output.mkdir(); (self.output / "keep").write_text("untouched")
        with self.assertRaises(ValueError):
            prepare(self.source, self.output, self.mp, self.pp, self.helpers)
        self.assertEqual((self.output / "keep").read_text(), "untouched")
        self.assertEqual(list(self.output.iterdir()), [self.output / "keep"])

    def test_changed_source_fails_before_output_creation(self):
        (self.source / "runtime/Strata/server.py").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "sealed input"):
            prepare(self.source, self.output, self.mp, self.pp, self.helpers)
        self.assertFalse(self.output.exists())

    def test_changed_preserved_helper_fails_before_output_creation(self):
        (self.helpers / "engine.py").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "helper lineage"):
            prepare(self.source, self.output, self.mp, self.pp, self.helpers)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
