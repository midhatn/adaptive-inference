# SPDX-License-Identifier: Apache-2.0
"""Two fixed task recipes sharing existing ownership, not an extensible registry.

The compiler contract is preserved. Video uses the existing checked NVENC
recipe and its own evidence. Selection is trusted task/deployment data, never
an import path or executable supplied by a model.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeDefinition:
    kind: str
    recipe_id: str
    tool_name: str
    toolset: str
    stages: tuple

    @property
    def request_schema(self): return self.kind + '-operation.v1'

    @property
    def result_schema(self): return self.kind + '-operation-result.v1'

    @property
    def receipt_schema(self): return self.kind + '-recipe.v1'

    @property
    def route(self): return '/_adaptive/' + self.kind + '-operation'

    @property
    def header(self): return 'X-Adaptive-' + self.kind.title() + '-Capability'

    @property
    def receipt_key(self): return self.kind + '_receipt'

    def contract(self, spec): return None if spec is None else getattr(spec, self.kind)

    def validate_args(self, spec, args, *, completed_runs=0):
        return getattr(spec, 'validate_' + self.kind + '_args')(args, completed_runs=completed_runs)

    def completion(self, spec, receipts):
        return getattr(spec, self.kind + '_completion')(receipts)

    def components(self):
        # Lazy imports avoid a task/recovery import cycle and do not load SDKs.
        if self.kind == 'compiler':
            from adaptive_inference.desktop.compiler_recipe import CompilerRecipe, run_recipe
            from adaptive_inference.desktop.compiler_template import CompilerSettings, prepare_cpp_recipe
            return CompilerSettings, CompilerRecipe, run_recipe, prepare_cpp_recipe
        from adaptive_inference.desktop.video_profile import VideoSettings
        from adaptive_inference.desktop.video_recipe import VideoRecipe, run_recipe
        from adaptive_inference.desktop.video_template import prepare_video_recipe
        return VideoSettings, VideoRecipe, run_recipe, prepare_video_recipe

    def tool_schema(self, spec):
        contract = self.contract(spec)
        properties = {'recipe_id': {'type': 'string', 'enum': [contract['recipe_id']]}}
        required = ['recipe_id']
        if self.kind == 'compiler':
            properties['source'] = {'type': 'string', 'minLength': 1, 'maxLength': contract['max_source_chars']}
            required.append('source')
            description = ('Compile and test C++17 source using this task\'s fixed recipe. '
                           'Compiler diagnostics can be corrected in a new attempt within the original allowance.')
        else:
            description = ('Create and verify the task\'s fixed three-second silent H.264 calibration clip. '
                           'The host owns encoding, probing, decoding and artifact verification.')
        return {'name': self.tool_name, 'description': description,
                'parameters': {'type': 'object', 'properties': properties,
                               'required': required, 'additionalProperties': False}}


_COMPILER = RecipeDefinition('compiler', 'cpp17-stdout.v1', 'build_and_test',
                             'adaptive_compiler', ('configure', 'build', 'test'))
_VIDEO = RecipeDefinition('video', 'nvenc-testclip.v1', 'encode_and_check_video',
                          'adaptive_video', ('encode', 'probe', 'decode'))


def definition(kind='compiler'):
    if kind == 'compiler': return _COMPILER
    if kind == 'video': return _VIDEO
    raise ValueError('Only the fixed compiler or video recipe is supported')


def recipe_kind(spec):
    kinds = [kind for kind in ('compiler', 'video') if spec is not None and getattr(spec, kind) is not None]
    if len(kinds) > 1:
        raise ValueError('One recipe capability per task is required')
    return kinds[0] if kinds else None


def completion_kwargs(spec, receipts):
    kind = recipe_kind(spec)
    return {'compiler_receipts': receipts} if kind is None else {kind + '_receipts': receipts}


def expected_tool_names(spec):
    kind = recipe_kind(spec)
    return {'read_file', 'write_file'} | ({definition(kind).tool_name} if kind else set())
