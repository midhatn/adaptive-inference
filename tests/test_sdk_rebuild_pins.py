"""Saved-conversation SDK pin/origin boundary; no SDK import or execution."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.installation import verify_sdk_imports
from adaptive_inference.desktop.hermes.sdk_pins import SDK_FILES


class RebuildPinTests(unittest.TestCase):
    def test_turn_context_is_in_the_production_disk_and_import_origin_map(self):
        self.assertEqual(SDK_FILES['agent/turn_context.py'],
            '89df9b4ad047d3efff4b3d3514cc4a6eef2ac05d6add105e1e4b354bee4191fa')

    def test_same_bytes_from_another_preloaded_sdk_origin_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            original=root/'sdk/agent/turn_context.py'
            alternate=root/'other-sdk/agent/turn_context.py'
            for path in (original,alternate):
                path.parent.mkdir(parents=True);path.write_bytes(b'# synthetic source-origin fixture\n')
            absent={name[:-3].replace('/','.'):None for name in SDK_FILES if name.endswith('.py')}
            module=SimpleNamespace(__file__=str(original))
            with mock.patch.dict(sys.modules,{**absent,'agent.turn_context':module}):
                verify_sdk_imports(root/'sdk')
                module.__file__=str(alternate)
                with self.assertRaisesRegex(RuntimeError,'agent.turn_context'):
                    verify_sdk_imports(root/'sdk')
                module.__file__=None
                with self.assertRaisesRegex(RuntimeError,'agent.turn_context'):
                    verify_sdk_imports(root/'sdk')
