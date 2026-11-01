"""Ordinary task preparation with real files; no host or provider execution."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from adaptive_inference import cli
from adaptive_inference.task_prepare import prepare_task
from adaptive_inference.task_spec import BUDGET, MAX_INPUT_BYTES, TaskSpec, digest


class TaskPrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / 'prepared'

    def test_selected_files_and_original_prompt_round_trip_into_existing_staging(self):
        prompt = '  Summarize notes.txt and data.csv in answer.txt. مرحبا.\r\n'
        originals = {'notes.txt': b'First note.\r\nSecond note.\n', 'data.csv': b'id,value\n1,23\n'}
        paths = []
        for name, raw in originals.items():
            path = self.root / name
            path.write_bytes(raw)
            paths.append(path)
        result = prepare_task(self.destination, prompt=prompt, inputs=paths)
        raw = Path(result['task_spec']).read_bytes()
        spec = TaskSpec.read(result['task_spec'], digest(raw))
        self.assertEqual(spec.prompt, prompt)
        self.assertEqual(spec.data['budget'], BUDGET)
        self.assertEqual(spec.data['outputs'], [{'name': 'answer.txt', 'required': True,
                                               'format': 'text', 'max_chars': 4096}])
        self.assertEqual(spec.data['validation'], {'validator': None})
        self.assertEqual(result['semantic_validation'], 'not_checked')
        work = self.root / 'work'
        work.mkdir()
        spec.stage_inputs(result['task_inputs'], work)
        for name, original in originals.items():
            self.assertEqual((self.root / name).read_bytes(), original)
            self.assertEqual((work / name).read_bytes(), original)
        paths[0].write_bytes(b'An edit after preparation.')
        spec.verify_inputs(result['task_inputs'])
        self.assertEqual((Path(result['task_inputs']) / 'notes.txt').read_bytes(), originals['notes.txt'])

    def test_cli_utf8_prompt_file_without_inputs_and_explicit_output(self):
        prompt = '  Write a greeting: مرحبا.\r\n'
        prompt_path = self.root / 'objective.txt'
        prompt_path.write_bytes(b'\xef\xbb\xbf' + prompt.encode('utf-8'))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(['prepare-task', '--destination', str(self.destination),
                '--prompt-file', str(prompt_path), '--output', 'greeting.json',
                '--format', 'json', '--max-chars', '500'])
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        spec = TaskSpec.from_bytes(Path(result['task_spec']).read_bytes())
        self.assertEqual(spec.prompt, prompt)
        self.assertEqual(spec.data['inputs'], [])
        self.assertEqual(spec.data['outputs'], [{'name': 'greeting.json', 'required': True,
                                               'format': 'json', 'max_chars': 500}])
        self.assertEqual(list(Path(result['task_inputs']).iterdir()), [])
        self.assertEqual(result['semantic_validation'], 'not_checked')

    def test_cli_repeated_inputs_and_default_output(self):
        paths = [self.root / name for name in ('one.txt', 'two.txt')]
        for path in paths:
            path.write_bytes(path.name.encode())
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(['prepare-task', '--destination', str(self.destination),
                '--prompt', 'Summarize both files.', '--input', str(paths[0]), '--input', str(paths[1])])
        self.assertEqual(code, 0)
        spec = TaskSpec.from_bytes((self.destination / 'task.json').read_bytes())
        self.assertEqual([row['name'] for row in spec.data['inputs']], ['one.txt', 'two.txt'])
        self.assertEqual(spec.data['outputs'][0]['name'], 'answer.txt')

    def test_invalid_declarations_fail_before_creating_destination(self):
        for options in ({'prompt': ' '}, {'output': '../answer.txt'}, {'max_chars': 4097},
                        {'output_format': 'binary'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                prepare_task(self.destination, **dict({'prompt': 'A useful task.'}, **options))
            self.assertFalse(self.destination.exists())
        first = self.root / 'one'
        second = self.root / 'two'
        first.mkdir(); second.mkdir()
        (first / 'notes.txt').write_bytes(b'one')
        (second / 'NOTES.TXT').write_bytes(b'two')
        with self.assertRaises(ValueError):
            prepare_task(self.destination, prompt='Summarize.', inputs=[first/'notes.txt', second/'NOTES.TXT'])
        self.assertFalse(self.destination.exists())

    def test_combined_input_bound_is_preserved_before_writes(self):
        paths = [self.root / name for name in ('one.txt', 'two.txt')]
        paths[0].write_bytes(b'x' * MAX_INPUT_BYTES)
        paths[1].write_bytes(b'y')
        with self.assertRaises(ValueError):
            prepare_task(self.destination, prompt='Summarize.', inputs=paths)
        self.assertFalse(self.destination.exists())

    def test_existing_destination_is_refused_without_modification(self):
        self.destination.mkdir()
        marker = self.destination / 'keep.txt'
        marker.write_bytes(b'Keep existing work.')
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = cli.main(['prepare-task', '--destination', str(self.destination), '--prompt', 'Task.'])
        self.assertEqual(code, 2)
        self.assertIn('must be new', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertEqual(list(self.destination.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b'Keep existing work.')

    def test_cli_requires_exactly_one_objective(self):
        for objective in ([], ['--prompt', 'Task.', '--prompt-file', 'objective.txt']):
            with self.subTest(objective=objective), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(['prepare-task', '--destination', str(self.destination), *objective])
            self.assertEqual(caught.exception.code, 2)
            self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
