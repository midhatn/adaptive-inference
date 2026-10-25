"""The narrow comparison adaptation must not erase source changes."""
import ast
import unittest

from ast_preservation import preservation_dump


class PreservationDumpTests(unittest.TestCase):
    def test_normalization_does_not_mutate_the_callers_tree(self):
        tree = ast.parse('class C:\n async def f(self):\n  return 1\ndef g():\n pass\n')
        before = ast.dump(tree, include_attributes=True)
        self.assertNotIn('type_params=', preservation_dump(tree))
        self.assertEqual(ast.dump(tree, include_attributes=True), before)

    def test_new_parameters_on_each_definition_are_rejected(self):
        for source in ('def f():\n pass\n', 'async def f():\n pass\n', 'class C:\n pass\n'):
            tree = ast.parse(source)
            tree.body[0].type_params = [ast.Name(id='T', ctx=ast.Load())]
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'type parameters'):
                preservation_dump(tree)
        # Exercise real Python 3.12 parser output as well as the 3.11-compatible
        # injected-field fixtures above; this is not a version-based test skip.
        if hasattr(ast, 'TypeVar'):
            for source in ('def f[T]():\n pass\n', 'async def f[T]():\n pass\n', 'class C[T]:\n pass\n'):
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'type parameters'):
                    preservation_dump(ast.parse(source))

    def test_invalid_empty_lookalike_field_values_are_not_ignored(self):
        for value in (None, (), '', False):
            tree = ast.parse('def f():\n pass\n')
            tree.body[0].type_params = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                preservation_dump(tree)

    def test_semantic_changes_remain_visible(self):
        original = '@decorate\ndef f(x=1):\n return x + 2\n'
        baseline = preservation_dump(ast.parse(original))
        for changed in (
            original.replace('decorate', 'other'), original.replace('x=1', 'x=2'),
            original.replace('x + 2', 'x - 2'), original.replace('x + 2', 'x + 3'),
            original.replace('def f', 'def changed'), original.replace('return x + 2', 'raise RuntimeError()')):
            with self.subTest(source=changed):
                self.assertNotEqual(preservation_dump(ast.parse(changed)), baseline)
        self.assertNotEqual(preservation_dump(ast.parse('class C(A):\n pass\n')),
                            preservation_dump(ast.parse('class C(B):\n pass\n')))

    def test_literal_text_is_never_rewritten_like_a_dump_string(self):
        first = preservation_dump(ast.parse("value = 'type_params=[]'"))
        second = preservation_dump(ast.parse("value = ''"))
        self.assertIn('type_params=[]', first)
        self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
