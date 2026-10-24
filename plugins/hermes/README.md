# Adaptive Inference routing for Hermes

This optional plugin marks host-known background work for an existing [Adaptive Inference](https://github.com/midhatn/adaptive-inference) gateway. Ordinary interactive requests keep their current routing. The gateway owns queuing, admission and resource checks; the plugin adds only `X-Adaptive-Class: background` to eligible chat-completions requests.

It uses public Hermes request middleware and lifecycle hooks. It does not replace core functions, create a provider, read credentials, start processes, contact a service or change prompts, models, tools, token limits, reasoning effort or sampling settings. Its only mutable state is a bounded in-memory index of delegated sessions. It has no Python dependencies beyond the standard library.

## Install and configure

Use an immutable commit of this repository that contains `plugins/hermes`. Installation uses Hermes's supported monorepo subdirectory syntax:

```text
hermes plugins install midhatn/adaptive-inference#plugins/hermes --ref FULL_40_CHARACTER_COMMIT
```

`FULL_40_CHARACTER_COMMIT` is a placeholder to replace with the reviewed plugin commit. The plugin is not represented as catalog-approved before its catalog entry is merged. For a source checkout or offline installation, copy this entire directory into the intended Hermes profile's `plugins/adaptive-inference-routing` directory using Hermes's documented local-plugin layout. Existing installed plugins should be managed through Hermes rather than overwritten.

Configure the intended Hermes provider to use `http://127.0.0.1:18100/v1`, preserving its actual model ID, credentials and quality settings. Enable the plugin in that same profile and merge this fragment into its existing configuration:

```yaml
plugins:
  enabled:
    - adaptive-inference-routing
  entries:
    adaptive-inference-routing:
      settings:
        routing:
          enabled: true
          gateway_url: http://127.0.0.1:18100/v1
          demote_delegated: true
          demote_cron: true
          background_profile: false
```

Do not replace an existing `plugins.enabled` list or other plugin settings. The plugin is inactive by default, even when installed. Invalid or unknown routing settings also leave requests unchanged. Enable it before starting delegated work.

The configured gateway URL must exactly match the request's scheme, hostname, port and `/v1` or `/background/v1` path. A trailing slash and the scheme's default port are normalized. Whitespace/control characters, backslashes, zero/out-of-range ports, user information, query strings, fragments, alternate paths and other API modes are rejected. Prefix paths such as `/proxy/v1` are not supported by this plugin. The plugin does not redirect a request to that URL; the Hermes provider configuration selects the endpoint.

## Work classification

- **Interactive requests:** unchanged. Text claiming to be a background task has no effect. `/btw` and other user work without a host background identity remain unchanged.
- **Delegated children in the same profile:** the host's `subagent_start` event enrolls the child session. `post_compaction` keeps its new session alias, and `subagent_stop` removes all aliases. The index has at most 2,048 aliases. If full, a warning is logged and additional unknown sessions keep their existing routing.
- **Cron:** a public `PluginContext.current_cron_execution()` identity marks the request when that capability exists. It is present on the tested current SDK, but absent from the retained Hermes 0.21.5 baseline. Older SDKs leave cron requests unchanged unless a dedicated background profile is configured.
- **Dedicated worker profiles:** set `background_profile: true` explicitly. This covers every eligible request from that profile, including children launched from another profile. Automatic child identity does not cross plugin-manager/profile boundaries.
- **Auxiliary calls:** Hermes's current auxiliary observation hook cannot rewrite requests, so this plugin does not claim automatic auxiliary classification. Configure an already selected auxiliary provider's `base_url` as `http://127.0.0.1:18100/background/v1`, retaining that provider's model, authentication, budgets and fallback policy. This is an explicit configuration route through the same gateway queue. Do not use a second gateway for priority isolation.

Explicit caller routing always wins. A pre-existing case-insensitive `X-Adaptive-Class` header or an `adaptive_scheduling`/`strata_scheduling` field is preserved, including malformed fields that the gateway may reject. The plugin never promotes work to normal or privileged status. Other plugins remain subject to Hermes's ordered middleware composition; this plugin does not enforce a global priority policy against later transformations.

Disabling or unloading the plugin stops its routing changes. Reloading loses its in-memory child identities; use an explicit background profile for durable worker classification. No claim is made about native unloading, GPU preemption, faster completion, model quality or autonomous task completion.

## Compatibility and evidence

The full source pins and public API references are recorded in `SOURCE_LOCK.json`. Tests live outside this installable directory in `integrations/hermes-plugin-tests` so admission scans only the plugin's production source.

- Retained Hermes `2587d8231fc7e0f3e846acafa46eb5b67cdc70c8` (0.21.5): 40 tests pass; one cron test is explicitly skipped because the public capability is absent.
- Current Hermes `14e1e43a23761b369641208e204365cd6cb9399d`: 41 tests pass, including cron context isolation.
- Tests execute the actual PluginManager, request middleware, host child-construction/stop event call sites and OpenAI SDK serialization. Agent construction in the child test and HTTP transport are fixtures. There is no model execution or actual network/backend qualification in these tests.
- The official admission pipeline validates declarations, source scanning and public registration. Its exact result is retained separately from contract tests; installation itself is not silently performed by this plugin.

The plugin's original code is licensed under Apache-2.0, matching the canonical repository. Hermes public contracts are from NousResearch/hermes-agent under MIT; no Hermes implementation is vendored into this plugin.
