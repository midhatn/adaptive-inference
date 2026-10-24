# Pinned Strata source integration

This optional integration reconstructs the native/HTTP engine used by the earlier local prototype. It is separate from this repository's generic gateway. It contains pinned sources, patches, tests and attribution, with upstream support/test assets preserved for exact identity. It supplies no workstation executable, full inference model, private run logs or machine installation paths.

The public base is [Strata 7ddc17a3](https://github.com/Niko1221/Strata/commit/7ddc17a38fe7f31637e895ecfba58c2cd43d65ec), the retained v0.2.3.1 baseline. The runtime overlay reproduces 87 selected changed files from local reference `c6b23493b01028a18a9eb685d0bb6435c6976316`. A separate patch applies the exact Windows token-default process-rights correction discussed in [Strata #3399](https://github.com/Niko1221/Strata/pull/3399). It changes three rights masks on one token-default DACL line; explicit file ACL helpers are unchanged.

## Reconstruct into a new directory

Run from the root of this repository with Python 3.11 or later and Git installed:

```sh
python integrations/strata/setup.py --output ../strata-adaptive-source
```

The output's parent must exist and the output must not exist, even as an empty directory. The script verifies the locally bundled baseline and complete 4,726-file inventory, restores the exact commit without network access, verifies both patches and all 88 changed-file hashes, and checks the complete final Git tree. It also restores the pinned 3,608-file llama.cpp source under `_adaptive_dependencies/llama.cpp`. It does not install dependencies, build, start a service or download models. Failed output is retained for inspection; existing checkouts are never reset or deleted. Global Git config, hooks and network transports are disabled. `.git/adaptive-integration.json` records the result.

Use `python integrations/strata/setup.py --verify-only` to check local inputs without creating an output. The baseline bundles and complete inventories live under [source](source), bound by [source-lock.json](source-lock.json). These are complete pinned snapshots without parent history, LFS dependencies or submodules. External PR links are citations; reconstruction does not follow them.

The checkout uses canonical Git blob bytes with LF line endings. The expected changed tree is `f2d6e86a0d49aaae47308904a1d5d9ea46e3b9a8`. The complete input and exclusions are in [source-lock.json](source-lock.json). The 44 excluded historical changes are benchmark records, old machine-specific documentation/CI and the historical Hermes private-hook plugin. Runtime/native/test code is retained; the exported source is deliberately not a byte-for-byte archive of every historical branch artifact.

## CPU checks

Install the pinned checkout's Python test dependencies in a separate environment. Then, from the reconstructed checkout:

```sh
python -m unittest serve.test_inference_queue tests.test_request_costs serve.test_inference_scheduling_service serve.test_coadaptive_route_wire serve.test_scheduling_preparation serve.test_scheduling_parking_feedback
```

This exact fresh reconstruction passed 54 CPU tests on Windows/Python 3.11.9. The service fixtures use fake engines and local HTTP; their token rates are not benchmarks. This repository's reconstruction admission checks run with `python -m unittest discover -s provenance -p "test_*.py"`.

## Build the native engine

The CUDA build needs a supported compiler, CMake, Ninja and CUDA Toolkit. The historical qualification used Windows, MSVC 14.44, CUDA 13.4 and architecture89 (RTX 4070 Laptop). Other hardware/toolchains need their own qualification. HIP, SYCL and Metal are not covered by that CUDA result.

The checkout's CMake pins ggml through llama.cpp commit [3cf03257](https://github.com/ggml-org/llama.cpp/commit/3cf03257f219afbe7334045ff7c6a06ac68c627d). The source is included and restored locally. Set `STRATA_GGML_DIR` to the **absolute** path of the restored `_adaptive_dependencies/llama.cpp` directory; omitting this override leaves upstream CMake's network-fetch behavior enabled. Review `README.md`, `docs/AI_SETUP.md` and the build documentation in the restored checkout and install toolchain prerequisites yourself. Setup does not execute a compiler or package installer. Replace the path placeholder and run in a configured compiler environment:

```sh
cmake -S ../strata-adaptive-source -B ../strata-adaptive-build -G Ninja -DSTRATA_GGML_DIR=REPLACE_WITH_ABSOLUTE_RESTORED_LLAMA_SOURCE -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON -DSTRATA_ENABLE_HIP=OFF -DSTRATA_ENABLE_SYCL=OFF -DCMAKE_CUDA_ARCHITECTURES=89 -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_PORTABLE=ON -DSTRATA_BUILD_TESTS=ON -DSTRATA_BUILD_CONVERSATION_TESTS=ON -DSTRATA_MMQ_KQUANTS=OFF -DSTRATA_Q6K_EXPERTS=OFF
cmake --build ../strata-adaptive-build --parallel 1 --target strata live_memory_test live_prefill_policy_test background_control_test request_stop_test pool_background_test pool_tasks_test platform_memory_test file_expert_source_test conversation_validation_test iq_avx2_parity router_dot_parity pool_cores_test numa_pool_test
```

Choose the architecture appropriate to your GPU;89 only reproduces the historical hardware target. Run the built test executables individually. `live_memory_test` uses `--protocol-only` for the historical non-model check; the other twelve test programs above run without arguments. On Windows the files have `.exe` suffixes. A matching source does not promise a bit-identical executable across compiler environments. The historical binary hash is evidence, not a downloadable artifact or a new-build expectation.

For the optional CPU vision helper, use the same restored `_adaptive_dependencies/llama.cpp` source. Replace the absolute-path placeholder:

```sh
cmake -S ../strata-adaptive-source/tools/vision -B ../strata-vision-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DLLAMA_DIR=REPLACE_WITH_ABSOLUTE_PINNED_LLAMA_SOURCE -DSTRATA_PORTABLE=ON -DSTRATA_VISION_CUDA=OFF -DSTRATA_VISION_HIP=OFF -DSTRATA_VISION_SYCL=OFF -DSTRATA_VISION_METAL=OFF
cmake --build ../strata-vision-build --parallel 1 --target strata-vision
```

## Configure a backend

Use the reconstructed server's documented configuration and your locally acquired compatible model/pack/tokenizer assets. [server.example.json](server.example.json) is an explicit placeholder template, not an auto-discovery installer. Replace every `REPLACE_...` value before use. Model acquisition, conversion and the model's own license are the operator's responsibility; the full inference weights are not included here. The restored checkout's `docs/AI_SETUP.md` preserves the upstream acquisition workflow; its [original source](https://github.com/Niko1221/Strata/blob/7ddc17a38fe7f31637e895ecfba58c2cd43d65ec/docs/AI_SETUP.md) remains a citation.

The example preserves the historical 65,536 context/high reasoning/8,192 thinking baseline. Main callers must also send the 10,923 total output cap shown in [request.example.json](request.example.json). Scheduling is opt-in and public callers can only self-demote to background; they cannot provide learned costs or preempt an active owner.

The earlier Windows supervisor's pre-spawn cache sizing and retained-process lifecycle are **not** included in these source overlays. The eager server start needs an operator-selected resident budget that fits current RAM/commit after startup overhead and headroom. Do not infer a fixed memory requirement or reuse the historical 32 GiB cap blindly. The generic gateway also does not own backend memory just because it forwards requests. See [legacy reproduction](../../docs/legacy-reproduction.md) for those boundaries.

Strata's MIT license, llama.cpp's MIT license and Finagle's Apache-2.0 notice are retained in [licenses](licenses) and [NOTICE](NOTICE). Original bundled third-party notices also remain inside each complete source snapshot.
