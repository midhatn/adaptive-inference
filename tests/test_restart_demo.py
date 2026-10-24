"""Contract acceptance against real short-lived subprocesses, without a model."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "examples/validation/restart_survival.py"
SPEC = importlib.util.spec_from_file_location("restart_survival", SOURCE)
DEMO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEMO)


class RestartDemoTests(unittest.TestCase):
    def test_real_process_restart_preserves_feedback_and_blocks_effect_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = DEMO.run_restart_demo(Path(temporary) / "proof")
            self.assertTrue(result["passed"])
            self.assertTrue(result["all_owned_workers_exited"])
            self.assertTrue(result["safe_checkpoint"]["original_prompt_retained"])
            self.assertTrue(result["safe_checkpoint"]["feedback_retained"])
            self.assertEqual(result["safe_checkpoint"]["attempts"], 2)
            self.assertEqual(result["safe_checkpoint"]["artifact_total"], 42)
            self.assertTrue(result["interrupted_effect"]["requires_reconciliation"])
            self.assertEqual(result["interrupted_effect"]["external_deliveries"], 1)
            self.assertFalse(result["physical_power_loss_tested"])
            self.assertFalse(result["model_used"])

    def test_existing_output_directory_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "preserve.txt"
            marker.write_text("existing user data", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                DEMO.run_restart_demo(temporary)
            self.assertEqual(marker.read_text(encoding="utf-8"), "existing user data")


if __name__ == "__main__":
    unittest.main()
