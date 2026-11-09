"""Exact outer input view for fixture-only timeout diagnostics.

Unknown bytes are never projected. Legacy disposable roots lacking this new
archive still pass their bytes to unchanged inner validators, which reject
unrecognized complete inputs. Retained source is parsed, never executed.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE = 'provenance/task-handover/continuation-timeout-diagnostics'
INPUTS = {'tests/test_continuation_host.py', 'tests/test_continuation_readiness.py',
          'tests/continuation_diagnostics_lineage.py', 'tests/admission_activity_lineage.py'}


def record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / ARCHIVE / 'source-lineage.json').read_bytes())


def predecessor(relative, data, root=None):
    data = preparation_predecessor(relative, data, root)
    if relative not in INPUTS:
        return data
    root = ROOT if root is None else root
    if not (root / ARCHIVE / 'source-lineage.json').exists():
        return data
    row = record(root)['files'][relative]
    expected = ARCHIVE + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed timeout diagnostic predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed timeout diagnostic predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed complete timeout diagnostic AST')
        return before
    return data


# Ordinary task authoring is a later source delta, not installed case17 evidence.
# Reuse this outer byte view; all inner historical assertions remain unchanged.
PREPARATION = 'provenance/task-preparation'


def preparation_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / PREPARATION / 'source-lineage.json').read_bytes())


def preparation_inputs(root=None):
    root = ROOT if root is None else root
    return ([root / PREPARATION / 'source-lineage.json', root / PREPARATION / 'cli.before.py']
            + reopen_inputs(root) + fixture_stop_inputs(root) + integration_inputs(root)
            + handover_inputs(root) + tool_capabilities_inputs(root) + reboot_budget_inputs(root))


def preparation_predecessor(relative, data, root=None):
    """Reverse only exact declared CLI/reader/version bytes, never unknown changes."""
    data = reopen_predecessor(relative, data, root)
    data = fixture_stop_predecessor(relative, data, root)
    root = ROOT if root is None else root
    if not (root / PREPARATION / 'source-lineage.json').exists():
        return data  # Legacy disposable roots still face the original checks.
    row = preparation_record(root)['files'].get(relative)
    if row is None or hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        return data
    if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
        raise AssertionError('Changed task-preparation successor AST')
    if relative == 'src/adaptive_inference/cli.py':
        if row['predecessor_source'] != PREPARATION + '/cli.before.py':
            raise AssertionError('Changed task-preparation predecessor path')
        before = (root / row['predecessor_source']).read_bytes()
    else:
        before = data
        for rule in reversed(row['replacements']):
            old, new = rule['old'].encode(), rule['new'].encode()
            if before.count(new) != rule['count']:
                raise AssertionError('Changed task-preparation reader edit')
            before = before.replace(new, old)
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed task-preparation predecessor identity')
    return before


def preparation_runtime_view(root=None):
    """Check declared addition/CLI/version deltas before historical closure checks.

    Every other module and byte passes through to those original assertions.
    No unknown module is omitted and no retained runtime is executed.
    """
    root = ROOT if root is None else root
    runtime = root / 'src/adaptive_inference'
    current = {path.relative_to(runtime).as_posix(): path.read_bytes()
               for path in runtime.rglob('*.py')}
    current = reopen_runtime_view(current, root)
    rows = preparation_record(root)
    for name, pin in {'task_prepare.py': rows['addition_sha256'],
                      '__init__.py': rows['files']['src/adaptive_inference/__init__.py']['successor_sha256'],
                      'cli.py': rows['files']['src/adaptive_inference/cli.py']['successor_sha256']}.items():
        if name not in current:
            raise AssertionError('Changed task-preparation runtime closure: ' + name)
        if hashlib.sha256(current[name]).hexdigest() != pin:
            raise AssertionError('Changed task-preparation runtime source: ' + name)
    del current['task_prepare.py']
    for name in ('cli.py', '__init__.py'):
        current[name] = preparation_predecessor('src/adaptive_inference/' + name, current[name], root)
    return current


def restore_preparation(tree, relative, root=None):
    """Existing AST readers see only the exact declared CLI/version deltas."""
    tree = restore_reopen(tree, relative, root)
    if relative not in ('cli.py', '__init__.py'):
        return tree
    root = ROOT if root is None else root
    source = 'src/adaptive_inference/' + relative
    row = preparation_record(root)['files'][source]
    if fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = (root / source).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete task-handover source (task-preparation): ' + relative)
    return ast.parse(preparation_predecessor(source, data, root))


# Saved-task reopening is prospective; the preparation record stays immutable.
REOPEN = 'provenance/installed-reopen'
REOPEN_RUNTIME = ('desktop/composition.py', 'desktop/hermes/run_recovery.py')
REOPEN_ADDITION = 'desktop/saved_tasks.py'


def reopen_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / REOPEN / 'source-lineage.json').read_bytes())


def reopen_inputs(root=None):
    root = ROOT if root is None else root
    return [root / REOPEN / 'source-lineage.json',
            *(root / row['predecessor_source'] for row in reopen_record(root)['files'].values())]


def reopen_predecessor(relative, data, root=None):
    """Project only a declared complete successor to its retained base bytes."""
    data = integration_predecessor(relative, data, 'reopen', root)
    root = ROOT if root is None else root
    if not (root / REOPEN / 'source-lineage.json').exists():
        return data
    row = reopen_record(root)['files'].get(relative)
    if row is None:
        return data
    expected = REOPEN + '/predecessor/' + relative
    if (not relative.startswith(('src/adaptive_inference/', 'tests/'))
            or '\\' in relative or any(part in ('', '.', '..') for part in relative.split('/'))
            or row['predecessor_source'] != expected):
        raise AssertionError('Changed installed-reopen predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed installed-reopen predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed installed-reopen successor AST')
        return before
    return data


def reopen_runtime_view(current, root=None):
    """Remove only the pinned addition and reverse the two declared modules."""
    current = handover_runtime_view(current, root)
    rows = reopen_record(root)
    expected = {REOPEN_ADDITION: rows['addition']['sha256']}
    expected.update({name: rows['files']['src/adaptive_inference/' + name]['successor_sha256']
                     for name in REOPEN_RUNTIME})
    for name, pin in expected.items():
        if name not in current:
            raise AssertionError('Changed installed-reopen runtime closure: ' + name)
        if hashlib.sha256(current[name]).hexdigest() != pin:
            raise AssertionError('Changed installed-reopen runtime source: ' + name)
    current = dict(current)
    del current[REOPEN_ADDITION]
    for name in REOPEN_RUNTIME:
        current[name] = reopen_predecessor('src/adaptive_inference/' + name, current[name], root)
    return current


def restore_reopen(tree, relative, root=None):
    tree = restore_handover(tree, relative, root)
    if relative not in REOPEN_RUNTIME:
        return tree
    root = ROOT if root is None else root
    source = 'src/adaptive_inference/' + relative
    row = reopen_record(root)['files'][source]
    if fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = handover_predecessor(source, (root / source).read_bytes(), root)
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete task-handover source (installed-reopen): ' + relative)
    return ast.parse(reopen_predecessor(source, data, root))


FIXTURE_STOP = 'provenance/task-handover/fixture-stop-verification'
FIXTURE_STOP_INPUTS = {'tests/test_continuation_host.py',
                       'tests/test_continuation_timeout_diagnostics.py',
                       'tests/continuation_timeout_lineage.py',
                       'tests/test_task_preparation_lineage.py'}


def fixture_stop_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / FIXTURE_STOP / 'source-lineage.json').read_bytes())


def fixture_stop_inputs(root=None):
    root = ROOT if root is None else root
    path = root / FIXTURE_STOP / 'source-lineage.json'
    if not path.exists():
        return []
    return [path, *(root / FIXTURE_STOP / 'predecessor' / relative
                    for relative in sorted(FIXTURE_STOP_INPUTS))]


def fixture_stop_predecessor(relative, data, root=None):
    """Map only complete approved fixture/reader bytes to their retained source."""
    data = integration_predecessor(relative, data, 'fixture_stop', root)
    root = ROOT if root is None else root
    if relative not in FIXTURE_STOP_INPUTS or not (root / FIXTURE_STOP / 'source-lineage.json').exists():
        return data
    row = fixture_stop_record(root)['files'][relative]
    expected = FIXTURE_STOP + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed fixture Stop verification predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed fixture Stop verification predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed complete fixture Stop verification successor AST')
        return before
    return data


# Compose the two reviewed reader deltas without rewriting their source records.
INTEGRATION = 'provenance/installed-reopen/fixture-stop-integration'
INTEGRATION_INPUTS = {'tests/continuation_timeout_lineage.py',
                      'tests/test_task_preparation_lineage.py'}


def integration_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / INTEGRATION / 'source-lineage.json').read_bytes())


def integration_inputs(root=None):
    root = ROOT if root is None else root
    path = root / INTEGRATION / 'source-lineage.json'
    if not path.exists():
        return []
    return [path, *(root / INTEGRATION / view / relative
                    for view in ('reopen', 'fixture_stop')
                    for relative in sorted(INTEGRATION_INPUTS))]


def integration_predecessor(relative, data, view, root=None):
    """Expose only a pinned combined reader as one exact retained branch view."""
    data = handover_predecessor(relative, data, root)
    root = ROOT if root is None else root
    if view not in ('reopen', 'fixture_stop'):
        raise AssertionError('Changed integrated reader view')
    if relative not in INTEGRATION_INPUTS or not (root / INTEGRATION / 'source-lineage.json').exists():
        return data
    row = integration_record(root)['files'][relative]
    retained = row['views'][view]
    expected = INTEGRATION + '/' + view + '/' + relative
    if retained['source'] != expected:
        raise AssertionError('Changed integrated reader predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != retained['sha256']
            or fingerprint(ast.parse(before)) != retained['ast_sha256']):
        raise AssertionError('Changed integrated reader predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed integrated reader successor AST')
        return before
    return data


# Later handover tasks reuse reopening; no historical receipt is requalified.
HANDOVER = 'provenance/installed-reopen/handover-tasks'
HANDOVER_RUNTIME = ('desktop/task_handover.py', 'desktop/saved_tasks.py')
HANDOVER_INPUTS = {'src/adaptive_inference/' + name for name in HANDOVER_RUNTIME} | {
    'tests/continuation_timeout_lineage.py', 'tests/test_task_preparation_lineage.py'}


def handover_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / HANDOVER / 'source-lineage.json').read_bytes())


def handover_inputs(root=None):
    root = ROOT if root is None else root
    path = root / HANDOVER / 'source-lineage.json'
    if not path.exists():
        return []
    return [path, *(root / HANDOVER / 'predecessor' / relative
                    for relative in sorted(HANDOVER_INPUTS))]


def handover_predecessor(relative, data, root=None):
    """Reverse only exact declared files; unknown bytes reach original checks."""
    data = tool_capabilities_predecessor(relative, data, root)
    root = ROOT if root is None else root
    if relative not in HANDOVER_INPUTS or not (root / HANDOVER / 'source-lineage.json').exists():
        return data
    row = handover_record(root)['files'][relative]
    expected = HANDOVER + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed handover-reopen predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed handover-reopen predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed handover-reopen successor AST')
        return before
    return data


def handover_runtime_view(current, root=None):
    """Project before saved_tasks is removed; preserve every other module."""
    result = tool_capabilities_runtime_view(current, root)
    for name in HANDOVER_RUNTIME:
        if name in result:
            result[name] = handover_predecessor('src/adaptive_inference/' + name, result[name], root)
    return result


def restore_handover(tree, relative, root=None):
    tree = restore_tool_capabilities(tree, relative, root)
    root = ROOT if root is None else root
    if relative not in HANDOVER_RUNTIME or not (root / HANDOVER / 'source-lineage.json').exists():
        return tree
    source = 'src/adaptive_inference/' + relative
    row = handover_record(root)['files'][source]
    if fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = reboot_budget_predecessor(source, (root / source).read_bytes(), root)
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete handover-reopen source: ' + relative)
    return ast.parse(handover_predecessor(source, data, root))


# Capability selection is prospective; installed and handover records stay exact.
TOOL_CAPABILITIES = 'provenance/installed-reopen/tool-capabilities'
TOOL_CAPABILITIES_RUNTIME = ('desktop/hermes/run_recovery.py',)
TOOL_CAPABILITIES_INPUTS = {'src/adaptive_inference/' + name for name in TOOL_CAPABILITIES_RUNTIME} | {
    'tests/continuation_timeout_lineage.py', 'tests/test_task_preparation_lineage.py',
    'tests/test_continuation_worker.py', 'tests/test_admission_wait_continuation_worker.py',
    'tests/safe_wait_fixture.py'}


def tool_capabilities_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / TOOL_CAPABILITIES / 'source-lineage.json').read_bytes())


def tool_capabilities_inputs(root=None):
    root = ROOT if root is None else root
    path = root / TOOL_CAPABILITIES / 'source-lineage.json'
    if not path.exists():
        return []
    return [path, *(root / TOOL_CAPABILITIES / 'predecessor' / relative
                    for relative in sorted(TOOL_CAPABILITIES_INPUTS))]


def tool_capabilities_predecessor(relative, data, root=None):
    """Reverse only reviewed complete source; preserve unknown bytes for refusal."""
    data = reboot_budget_predecessor(relative, data, root)
    root = ROOT if root is None else root
    if relative not in TOOL_CAPABILITIES_INPUTS or not (root / TOOL_CAPABILITIES / 'source-lineage.json').exists():
        return data
    row = tool_capabilities_record(root)['files'][relative]
    expected = TOOL_CAPABILITIES + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed tool-capability predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed tool-capability predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed tool-capability successor AST')
        return before
    return data


def tool_capabilities_runtime_view(current, root=None):
    result = reboot_budget_runtime_view(current, root)
    for name in TOOL_CAPABILITIES_RUNTIME:
        if name in result:
            result[name] = tool_capabilities_predecessor('src/adaptive_inference/' + name, result[name], root)
    return result


def restore_tool_capabilities(tree, relative, root=None):
    tree = restore_reboot_budget(tree, relative, root)
    root = ROOT if root is None else root
    if relative not in TOOL_CAPABILITIES_RUNTIME or not (root / TOOL_CAPABILITIES / 'source-lineage.json').exists():
        return tree
    source = 'src/adaptive_inference/' + relative
    row = tool_capabilities_record(root)['files'][source]
    if fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = reboot_budget_predecessor(source, (root / source).read_bytes(), root)
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete tool-capability source: ' + relative)
    return ast.parse(tool_capabilities_predecessor(source, data, root))


# Versioned reboot allowance is a new contract, not a renewal of historical runs.
REBOOT_BUDGET = 'provenance/installed-reopen/reboot-budget'
REBOOT_BUDGET_RUNTIME = ('execution_clock.py', 'desktop/saved_tasks.py',
    'desktop/composition.py', 'desktop/task_handover.py', 'desktop/hermes/run_recovery.py',
    'desktop/hermes/service_stop.py', 'desktop/hermes/continuation.py')
REBOOT_BUDGET_ADDITION = 'desktop/execution_budget.py'
REBOOT_BUDGET_INPUTS = {'src/adaptive_inference/' + name for name in REBOOT_BUDGET_RUNTIME} | {
    'tests/continuation_timeout_lineage.py', 'tests/test_task_preparation_lineage.py'}


def reboot_budget_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / REBOOT_BUDGET / 'source-lineage.json').read_bytes())


def reboot_budget_inputs(root=None):
    root = ROOT if root is None else root
    path = root / REBOOT_BUDGET / 'source-lineage.json'
    if not path.exists():
        return []
    return [path, *(root / REBOOT_BUDGET / 'predecessor' / relative
                    for relative in sorted(REBOOT_BUDGET_INPUTS))]


def reboot_budget_predecessor(relative, data, root=None):
    """Restore only exact reviewed bytes; unknown changes reach old validators."""
    root = ROOT if root is None else root
    if relative not in REBOOT_BUDGET_INPUTS or not (root / REBOOT_BUDGET / 'source-lineage.json').exists():
        return data
    row = reboot_budget_record(root)['files'][relative]
    expected = REBOOT_BUDGET + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed reboot-budget predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed reboot-budget predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed reboot-budget successor AST')
        return before
    return data


def reboot_budget_runtime_view(current, root=None):
    """Remove only the exact addition before the unchanged historical closures."""
    root = ROOT if root is None else root
    result = dict(current)
    if not (root / REBOOT_BUDGET / 'source-lineage.json').exists():
        return result
    addition = reboot_budget_record(root)['addition']
    if addition['source'] != 'src/adaptive_inference/' + REBOOT_BUDGET_ADDITION:
        raise AssertionError('Changed reboot-budget addition path')
    if REBOOT_BUDGET_ADDITION not in result:
        raise AssertionError('Changed reboot-budget runtime closure: ' + REBOOT_BUDGET_ADDITION)
    data = result[REBOOT_BUDGET_ADDITION]
    if (hashlib.sha256(data).hexdigest() != addition['sha256']
            or fingerprint(ast.parse(data)) != addition['ast_sha256']):
        raise AssertionError('Changed reboot-budget runtime source: ' + REBOOT_BUDGET_ADDITION)
    del result[REBOOT_BUDGET_ADDITION]
    for name in REBOOT_BUDGET_RUNTIME:
        if name in result:
            result[name] = reboot_budget_predecessor('src/adaptive_inference/' + name, result[name], root)
    return result


def restore_reboot_budget(tree, relative, root=None):
    root = ROOT if root is None else root
    if relative not in REBOOT_BUDGET_RUNTIME or not (root / REBOOT_BUDGET / 'source-lineage.json').exists():
        return tree
    source = 'src/adaptive_inference/' + relative
    row = reboot_budget_record(root)['files'][source]
    if fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = (root / source).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete reboot-budget source: ' + relative)
    return ast.parse(reboot_budget_predecessor(source, data, root))
