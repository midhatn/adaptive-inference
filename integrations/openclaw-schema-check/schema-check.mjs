// Evaluate the exact upstream schema modules; no OpenClaw service or model.
import { registerHooks } from 'node:module';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const reference = new URL('./reference/', import.meta.url);
registerHooks({resolve(specifier, context, nextResolve) {
  const alias = {
    '@openclaw/model-catalog-core/model-catalog-refs': 'packages/model-catalog-core/src/model-catalog-refs.ts',
    '@openclaw/normalization-core/string-coerce': 'packages/normalization-core/src/string-coerce.ts',
  }[specifier];
  if (alias) return {url: new URL(alias, reference).href, shortCircuit: true};
  if (specifier.startsWith('.') && specifier.endsWith('.js') && context.parentURL) {
    const url = new URL(specifier.slice(0, -3) + '.ts', context.parentURL);
    if (existsSync(fileURLToPath(url))) return {url: url.href, shortCircuit: true};
  }
  return nextResolve(specifier, context);
}});
const { AgentDefaultsBaseSchema } = await import('./reference/src/config/zod-schema.agent-defaults-base.ts');
const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const validated = AgentDefaultsBaseSchema.parse(input.agents.defaults);
assert.deepEqual(validated, input.agents.defaults);
assert.equal(validated.model.primary, 'adaptive/existing-IQ3_S');
assert.equal(validated.subagents.model.primary, 'adaptive-background/existing-IQ3_S');
assert.equal(validated.thinkingDefault, 'high');
assert.equal(validated.models['adaptive-background/existing-IQ3_S'].params.reasoning_budget_tokens, 8192);
assert.throws(() => AgentDefaultsBaseSchema.parse({...input.agents.defaults, subagents: {model: 5}}));
console.log(JSON.stringify({passed: true, source: '237fdc662d90d216a8693fa6b9178afc0cbc54d6',
  scope: 'actual AgentDefaultsBaseSchema only; no service, full config, transport or model validation'}));
