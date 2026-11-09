# Let the agent compile and test a small program

Select [task.json](task.json) in the existing desktop launcher. The task asks the
agent to produce C++17 source that prints exactly `23 units`, with no newline,
then use the bounded `build_and_test` tool. A compiler error can be returned to
the same conversation for correction. The task permits at most two builds inside
its original 900-second allowance; it does not require an initial failed build.

This example needs the compiler-enabled source and matching installed wheel.
Follow the [desktop setup prerequisites](../../desktop/README.md) first, retaining
the supported full Python host and worker, pinned Hermes interfaces, and existing
IQ3_S model and quality settings. The previously released file-only alpha does
not gain this compiler capability just by copying the task file.

## Prepare your local compiler settings

Use existing CMake 3.29 or newer, CTest, Ninja, LLVM `clang-cl.exe` and
`lld-link.exe`, plus MSVC C++ headers/libraries and the Windows SDK. Open your
installation's **x64 Developer PowerShell** so its compiler environment is
already initialized. Microsoft's [developer environment guidance](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line?view=msvc-170)
explains why these paths depend on the installed tools. LLVM documents the
[clang-cl interface](https://clang.llvm.org/docs/UsersManual.html#clang-cl) and
[Windows linker](https://lld.llvm.org/windows_support.html). No installer or
compiler-discovery service is added here.

Replace the five example tool paths and output path below with your own. The
output's parent folder must exist. This prepares settings only; it does not
start a compiler or model. It copies the listed build variables, rather than
your whole shell environment. Keep this machine-specific file outside Git.

```powershell
$toolPaths = [ordered]@{
  cmake = 'C:/Program Files/CMake/bin/cmake.exe'
  ctest = 'C:/Program Files/CMake/bin/ctest.exe'
  compiler = 'C:/Program Files/LLVM/bin/clang-cl.exe'
  ninja = 'C:/Tools/Ninja/ninja.exe'
  linker = 'C:/Program Files/LLVM/bin/lld-link.exe'
}
$settingsPath = 'D:/Adaptive Settings/compiler-settings.json'
if (Test-Path -LiteralPath $settingsPath) { throw 'Choose a new settings file.' }
$buildEnvironment = [ordered]@{}
foreach ($name in @('PATH', 'INCLUDE', 'LIB', 'LIBPATH', 'SystemRoot',
                    'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP')) {
  $value = [Environment]::GetEnvironmentVariable($name)
  if ($value) { $buildEnvironment[$name] = $value }
}
foreach ($name in @('PATH', 'INCLUDE', 'LIB', 'SystemRoot', 'TEMP', 'TMP')) {
  if (-not $buildEnvironment[$name]) { throw "Missing developer environment: $name" }
}
$settings = [ordered]@{
  schema = 'adaptive.compiler-settings.v1'
  environment = $buildEnvironment
}
foreach ($name in $toolPaths.Keys) {
  $file = Get-Item -LiteralPath $toolPaths[$name] -ErrorAction Stop
  $settings[$name] = @{
    path = $file.FullName
    sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}
[IO.File]::WriteAllText($settingsPath,
  ($settings | ConvertTo-Json -Depth 5) + [Environment]::NewLine,
  [Text.UTF8Encoding]::new($false))
```

Run the existing setup command with the optional settings file. Use a new
destination and your actual installed component paths:

```powershell
& 'C:/Python311/python.exe' -I -B 'D:/adaptive-inference/examples/desktop/setup.py' `
  --destination 'D:/Adaptive Compiler Desktop' `
  --worker-python 'D:/Python314/python.exe' `
  --hermes-source 'D:/Agents/hermes-pinned-source' `
  --hermes-site-packages 'D:/Agents/hermes-environment/Lib/site-packages' `
  --native-owner 'D:/Models/owned-strata-profile' `
  --compiler-settings 'D:/Adaptive Settings/compiler-settings.json'
```

Setup reuses the runtime's compiler-settings parser and checks all five tool
hashes before creating the launcher. Omitting the option preserves file-only
setup. Later tool updates require explicitly preparing a fresh settings/profile;
setup does not silently accept changed executables. Successful setup establishes
configuration validity, not a successful build or real resource handoff.

## Run and inspect the result

Open **Start Adaptive Inference.cmd**, select **New task**, choose this
`task.json`, then select **Resume** in the existing control window. This task has
no input files, so no input-folder selection is needed. **Stop** remains the
ordinary control for ending the active run.

The host supplies trusted CMake and CTest configuration, output locations, a
two-job build request, a 2048 MiB job committed-memory cap and a 90-second recipe
cap within the task's remaining time. The agent supplies bounded C++ source;
it cannot select shell commands, compiler paths or build-system code. These
process/resource limits are not a filesystem or network sandbox: use this
example for trusted local C++ workloads.

Successful completion requires the retained compiler receipt, executable,
exact stdout bytes, zero exit record and CTest report. A final chat answer alone
cannot satisfy it. `validation.validator: null` leaves the file-output validator
unset; the compiler contract still requires its successful receipt. Compiler
artifacts belong to the recipe operation, so `outputs` is intentionally empty.

The [compiler recipe guide](../../../docs/compiler-tool-recipe.md) describes
implementation and current evidence. Scripted-provider SDK checks, an actual
IQ3_S task, measured foreground handoff and computer-restart recovery are
separate qualifications. Selecting this example does not certify those gates.

This example reuses the repository's Apache-2.0 task, profile and launcher
contracts and Python's existing [argument parser](https://docs.python.org/3.11/library/argparse.html).
The sources above were checked on 2 November 2026; no upstream implementation
was copied for this setup option.
