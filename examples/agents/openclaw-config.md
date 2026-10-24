# OpenClaw background-provider configuration

OpenClaw already supports custom OpenAI-compatible providers and a default model for host-created subagents. This helper composes those existing interfaces into a reviewable configuration fragment for one Adaptive Inference gateway. It does not install an OpenClaw plugin or change a running application.

Supply your existing provider (already pointed at the intended gateway's normal `/v1` URL) and agent defaults. The helper clones the provider under a new background ID, changes only that clone's URL to `/background/v1`, and assigns the clone as the default child route. Both paths belong to the same gateway queue. Explicit reverse-proxy prefixes are retained using the canonical `gateway_client_options` helper; the proxy must forward both routes correctly.

```text
python examples/agents/openclaw_config.py --input existing-openclaw.json --provider adaptive --model YOUR_EXISTING_MODEL_ID --background-provider adaptive-background --output NEW-fragment.json
```

The command writes a new fragment only and refuses an existing output or background provider ID. It accepts JSON, not JSON5. Review and merge the fragment using OpenClaw's supported additive configuration tooling. Do not replace an entire existing configuration with the fragment. It can contain your existing credentials or SecretRef objects: keep it private and do not upload it. It does not resolve secrets or send requests.

The `build_config(provider, agent_defaults, *, provider_id, model_id, background_provider_id)` function is also available to host code. It preserves provider authentication, static headers, transport settings, model rows, capabilities, context/output limits, main selection, fallback lists and declared generation parameters. The source model's per-model settings are copied to the new exact reference, with its optional picker alias omitted to avoid creating two routes with the same alias. Global thinking/parameters and explicit subagent thinking/concurrency remain unchanged. No output cap, model identity, reasoning budget or fallback is invented.

An explicitly different child model, existing background model settings, conflicting priority header, unsupported API, ambiguous model row or restrictive model policy that does not explicitly allow the new reference is refused. The helper does not broaden an allowlist. Wildcard policies are conservatively refused unless the exact background reference is also present; policy evaluation belongs to OpenClaw.

This changes the global child default. Per-agent `subagents.model`, per-spawn model choices, persisted session overrides and configured fallbacks retain OpenClaw's normal precedence and may select another route. Configure those explicitly when they should run in the background. Existing per-agent model settings and agent-owned `models.json` can override global settings; review them before deployment. The helper does not enumerate or modify those stores.

For scheduled jobs, use OpenClaw's documented explicit job `--model adaptive-background/YOUR_EXISTING_MODEL_ID` selection while retaining the job's thinking and fallback settings. No cron job is created or changed by this helper. Auxiliary/utility routes require their own explicit configuration; they are not silently reclassified.

## Evidence and supported surface

The source pin is OpenClaw `237fdc662d90d216a8693fa6b9178afc0cbc54d6`. Current official contracts:

- [Custom provider and exact-origin trust configuration](https://github.com/openclaw/openclaw/blob/237fdc662d90d216a8693fa6b9178afc0cbc54d6/docs/gateway/config-tools/custom-providers.md).
- [Subagent configured-model precedence](https://github.com/openclaw/openclaw/blob/237fdc662d90d216a8693fa6b9178afc0cbc54d6/src/agents/model-selection-config.ts#L24).
- [Native default-agent schema](https://github.com/openclaw/openclaw/blob/237fdc662d90d216a8693fa6b9178afc0cbc54d6/src/config/zod-schema.agent-defaults-base.ts#L230).
- [Scheduled job model and thinking overrides](https://github.com/openclaw/openclaw/blob/237fdc662d90d216a8693fa6b9178afc0cbc54d6/docs/automation/cron-jobs/payloads.md#L34).

Fourteen focused Python tests cover copy isolation, preserved provider/model settings and fallback policy, endpoint prefixes, refusal boundaries and the executable command's no-overwrite behavior. A separate CPU test executes the exact pinned upstream `AgentDefaultsBaseSchema` with its complete small dependency closure and the upstream-pinned Zod 4.6.7. The generated agent defaults survive validation without transformations; an invalid child model is rejected. Source Git blob identities and npm integrity are recorded in the schema fixture.

These checks do not execute OpenClaw's full configuration loader, model resolver, guarded HTTP transport or agent. The Node interpreter used for the schema-only check is 24.14.0; full current OpenClaw requires a newer version and is not claimed as tested. No model, network inference, GPU/native resource behavior, throughput gain or completed agent task is inferred from the fixture results. The schema fixture itself needs only its pinned npm dependency, not an OpenClaw service.
