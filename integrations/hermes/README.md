# Pinned Hermes host-intent integration

This optional seven-file overlay starts from public [Hermes 2587d823](https://github.com/NousResearch/hermes-agent/commit/2587d8231fc7e0f3e846acafa46eb5b67cdc70c8) and reconstructs local reference `eaa9b473e5fab3fa94258f17ed6941aabba73d2d`. It adds host-declared background intent only for explicitly opted-in custom Strata routes. The generic gateway in this repository can also accept other clients; Hermes is not a core dependency.

From the repository root, with Python and Git installed:

```sh
python integrations/hermes/setup.py --output ../hermes-intent-source
```

The parent must exist and output must be new. Setup verifies the locally included Git bundle and complete 16,781-file baseline inventory, restores the exact commit without network access, checks/applies the patch and verifies all seven changed-file hashes and the complete final tree. It neither installs dependencies nor launches an agent. Global Git config/hooks and Git network transports are disabled. Existing destinations are refused without modification; failed new output is retained. Expected reconstructed tree: `516c9e3a951d5ba5894c5933fda3b833209e5c47`.

Use `python integrations/hermes/setup.py --verify-only` to check the local inputs without creating an output. The source bundle and inventory live under [source](source); [source-lock.json](source-lock.json) binds their hashes. The original PR and repository are citations, not reconstruction dependencies. The bundled commit is a complete source snapshot with no parent history, LFS dependency or submodules.

Follow the pinned upstream package-manager instructions in that checkout for a separate Hermes environment. Its supported runtime at this revision is Python3.14; the older-Python declaration exists for updater compatibility. Then run:

```sh
python -m pytest tests/agent/test_request_scheduling.py -q
```

Use a separate `HERMES_HOME` for testing and operation. [provider.example.yaml](provider.example.yaml) is a portable route fragment; replace the model name and endpoint for your backend. The opt-in checks the resolved provider, endpoint and model. Host-created subagents, cron/background-review origins and named auxiliary tasks self-demote; ordinary user and `/btw` work remains normal. No inference from prompt content or user-agent strings is used. See the reconstructed `website/docs/developer-guide/request-scheduling.md` for the full contract.

The main wire example keeps `max_tokens: 10923`, top-level `reasoning_budget_tokens: 8192`, high reasoning and projection disabled. The ordinary CLI's compressor reservation does not yet derive its reserve from that provider-level cap. The earlier qualified parent/child fixture explicitly passed `max_tokens=10923` to the constructor; do not claim the same compression threshold from this YAML alone. Auxiliary tasks have separate budgets and should be configured explicitly.

The historical private `authorized_tool_execution`/resource-feedback hooks and plugin are not part of this overlay. This is request intent tagging, not proof that tool execution is protected by a resource lease. Model/provider credentials and user history are not included.

The original MIT license is preserved in [licenses/UPSTREAM-LICENSE.txt](licenses/UPSTREAM-LICENSE.txt). Source pins and patch hashes are in [source-lock.json](source-lock.json).
