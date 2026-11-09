# Ask the agent for a checked GPU video clip

This development example lets an explicitly opted-in task request one fixed,
silent three-second H.264 calibration clip: 1280 by 720 pixels, 30 frames per
second, 90 frames total. The host runs NVENC encoding, FFprobe inspection and
full decoding before returning the artifact identity to the agent. This is a
small GPU-tool handoff; it is not the H3 autonomous media test or an audio-quality
measurement.

Use the video-enabled source and a matching installed package. Follow the
[desktop prerequisites](../../desktop/README.md) with the supported host and
worker, pinned Hermes interfaces, and the existing IQ3_S model and quality
settings. Copying this task into an older file-only installation does not add
video capability. Development validation is recorded in the
[recipe notes](../../../docs/video-tool-recipe.md); check their scope before use.

## Prepare the installed tools

Select an existing FFmpeg build with `h264_nvenc` support and its matching
FFprobe. NVIDIA's [FFmpeg guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html)
describes the build/driver requirements. The project calls these external
programs and does not distribute them. Keep your selected build's version,
configuration and [license information](https://ffmpeg.org/legal.html).

Replace the two absolute paths below with ordinary files in your installation,
and choose a new settings-file path under an existing folder. This captures
explicit tool identities and the small execution environment; it runs no media
or model workload.

```powershell
$videoToolPaths = [ordered]@{
  ffmpeg = 'C:/Tools/FFmpeg/bin/ffmpeg.exe'
  ffprobe = 'C:/Tools/FFmpeg/bin/ffprobe.exe'
}
$videoSettingsPath = 'D:/Adaptive Settings/video-settings.json'
if (Test-Path -LiteralPath $videoSettingsPath) { throw 'Choose a new settings file.' }
$videoEnvironment = [ordered]@{}
foreach ($name in @('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP')) {
  $value = [Environment]::GetEnvironmentVariable($name)
  if ($value) { $videoEnvironment[$name] = $value }
}
$videoSettings = [ordered]@{
  schema = 'adaptive.video-settings.v1'
  environment = $videoEnvironment
}
foreach ($name in $videoToolPaths.Keys) {
  $file = Get-Item -LiteralPath $videoToolPaths[$name] -ErrorAction Stop
  $videoSettings[$name] = @{
    path = $file.FullName
    sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}
[IO.File]::WriteAllText($videoSettingsPath,
  ($videoSettings | ConvertTo-Json -Depth 5) + [Environment]::NewLine,
  [Text.UTF8Encoding]::new($false))
```

Pass that file to the existing desktop setup helper, with your actual installed
component locations and a new destination:

```powershell
& 'C:/Python311/python.exe' -I -B 'D:/adaptive-inference/examples/desktop/setup.py' `
  --destination 'D:/Adaptive Video Desktop' `
  --worker-python 'C:/Python314/python.exe' `
  --hermes-source 'D:/Agents/hermes-pinned-source' `
  --hermes-site-packages 'D:/Agents/hermes-environment/Lib/site-packages' `
  --native-owner 'D:/Models/owned-strata-profile' `
  --video-settings 'D:/Adaptive Settings/video-settings.json'
```

This first increment selects either video or compiler settings for a controller
installation. File tasks remain available in either. Switching between both
useful-tool families in one retained controller is a later integration gate.
Changed executable bytes require a freshly selected and validated profile.

## Run and inspect

Open **Start Adaptive Inference.cmd**, choose **New task**, select
[task.json](task.json), then choose **Resume**. The task needs no input files.
The agent can request only `encode_and_check_video` with the fixed recipe ID;
the host chooses executable arguments and the fresh artifact location.

The original task allowance is 900 seconds with at most two video operations.
Each operation has a single 90-second allowance including the resource wait.
The initial resource request is 8 GiB RAM, 12 GiB commit and 6000 MiB VRAM,
reused from the earlier checked video handoff. These are conservative admission
requirements, not measured minima or operating-system reservations. The owned
process job separately has a 2048 MiB committed-memory cap.

Completion requires successful encode, exact probe facts, successful full decode,
a nonempty hashed artifact, and confirmed owned-process exits. The actual result
must persist into the agent's conversation. A final answer alone cannot replace
that evidence. The output is `handoff-video.mp4` inside the selected operation's
run directory. **Stop** uses the existing retained cleanup path.
