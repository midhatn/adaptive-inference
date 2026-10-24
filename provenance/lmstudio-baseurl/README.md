# LM Studio OpenAI-client option regression

This fixture reproduces the TypeScript constructor in the [LM Studio OpenAI-compatibility guide](https://github.com/lmstudio-ai/docs/blob/8c7159be3ffe364af10aa8ae6f5a7570e9402089/1_developer/3_openai-compat/index.mdx#L72) at revision `8c7159be3ffe364af10aa8ae6f5a7570e9402089`. Only its short constructor example is retained; the full documentation page is not bundled.

The original uses `baseUrl`. The OpenAI JavaScript SDK recognizes `baseURL`. With the environment base override removed, the original JavaScript constructor ignores the intended local address and uses the SDK's default API origin. TypeScript flags the unknown option.

Run with Node.js 22 or later:

```text
npm ci --ignore-scripts --no-audit --no-fund
node check-example.mjs
```

The lockfile pins `openai@7.43.0`, `typescript@7.0.2` and their dependencies. The test extracts no remote content at runtime: it verifies the locally retained constructor's hash, typechecks the original and corrected variants, then asks the real SDK to construct one Chat Completions request for each. A fake fetch function captures the request and returns a fixture response; a socket-connect guard fails any attempted connection. The supplied key is an explicit dummy string, and the environment's base-address override is removed.

The accepted run on Node.js 24.14.0 demonstrates:

- Original TypeScript: TS2561, unknown `baseUrl`; corrected TypeScript: clean.
- Original constructed address: `https://api.openai.com/v1/chat/completions`.
- Corrected constructed address: `http://localhost:1234/v1/chat/completions`.
- Identical request bodies and zero socket attempts.

The model identifier and output settings in the request are fixture data. No model runs and no request reaches LM Studio or OpenAI. This verifies SDK construction, not LM Studio inference or native resource behavior.

The SDK source revision observed during the initial source review is recorded separately from npm's published `gitHead`; the tested package is identified by its version and package-lock integrity. Original and corrected constructor hashes, source-document identity, compiler versions and results are in [result.json](result.json). The checked [PR #139](https://github.com/lmstudio-ai/docs/pull/139) was already merged and changed only the endpoint table in the related page; it did not fix this option. All-state PR searches for `baseUrl` and `baseURL` returned no matching proposals at review time.

The initial local test harness assumed the older TypeScript diagnostic exit status 2. TypeScript 7 returned status 1 with the expected TS2561 diagnostic. The expectation was corrected before the accepted run; the original and corrected SDK behaviors were not changed.

References: [official SDK documentation](https://developers.openai.com/api/reference/typescript), [published SDK source](https://github.com/openai/openai-node/tree/d02d4de77ea7a6f82325c02e6f44deb34ee3992c). The regression harness is new project code; the minimal retained constructor is attributed to the linked LM Studio documentation. Upstream SDK licenses remain in their installed packages.

