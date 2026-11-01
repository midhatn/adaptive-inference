# Manual local video observation

This small preparation tool serves one explicitly selected local video on
`127.0.0.1`. A person opens the printed URL in an ordinary browser and clicks
**Start measurement**. The page plays from the beginning, waits a fixed
10-second warm-up, then requests a 180-second observation window and pauses.
It never starts an agent, inference engine, telemetry session, or PresentMon.

Use an existing project installation with its pinned aiohttp dependency:

```powershell
python examples/validation/video_coexistence/serve.py `
  --video "C:\media\bbb_sunflower_1080p_60fps_normal.mp4" `
  --output "C:\measurements\video-baseline-before-01" `
  --condition baseline-before `
  --notes "Record display, power mode, browser/driver versions, HAGS and external run references here."
```

The output directory must not exist. Port 0 chooses a free loopback port; an
explicit `--port` is optional. No browser is opened automatically. The printed
per-run URL is local access information. Keep the page visible and playback
settings unchanged during the run. Use the normal video controls before a run
as needed; Start resets position and playback rate. Pause, seek, speed changes,
early end, hiding the page, or **Stop and save incomplete** end the observation
as incomplete. Waiting/stalled events are recorded as observations without
automatically ending a measurement. A media error records an error.

The page pauses when observation ends and saves its final report. Ctrl+C stops the server;
the controller and any separately owned capture have their own lifecycles.
Each baseline/adaptive/repeated run needs a new server output directory. The
`--condition` label identifies the intended comparison; it does not activate
or verify that condition. The unchanged IQ3_S task and its original budgets
remain entirely outside this page.

## What is saved

`result.private.json` begins as incomplete and records the clip's absolute path,
size and SHA-256, observation-source hashes, Python/aiohttp versions, declared
condition/notes, fixed settings and browser-reported display/playback settings.
It is private local evidence; do not commit personal paths or operator notes.
Browser timestamps, their time origin and server UTC timestamps are retained;
they are not a calibrated physical or ETW clock synchronization.

The warm-up and final counter snapshots yield **dropped frames / total frames**.
The W3C total already includes dropped frames; dropped frames are not added
again to the denominator. Decreasing/reset counters or no frame progress cannot
produce a completed result. Up to 220 one-second progression samples and 256
playback events are retained; truncation prevents a completed result.

`requestVideoFrameCallback` supplies compositor-submission metadata and a
bounded aggregate of callback delivery gaps and skipped callbacks. A busy main
thread can miss callbacks while video continues. These observations therefore
do **not** establish physical display stalls or replace the browser's dropped
frame counter. One-second samples also cannot prove absence of a 250-ms stall.
Media waiting/stalled events describe the media element, not independently
measured display latency. PresentMon remains a separate later capture tool.

The requested measurement window is fixed at 180 seconds. The actual elapsed
time and finish-timer lateness are saved rather than pretending browser timers
fire exactly on schedule. `completed` means the observation window finished
with valid counters, not that a responsiveness threshold or M3 passed. Compare
actual durations and identical setup before making performance claims.

A closed/crashed browser or interrupted server may leave only the initial or
started incomplete record. Closing a page attempts a final keepalive report,
but browser delivery is not guaranteed. A missing terminal report is never
converted into success. The first saved terminal report cannot be overwritten.

This tool does not validate audio realism/synchronization, hardware decoding,
GPU attribution, actual display refresh, native resource release, background
task correctness or complete desktop coexistence. Freeze those prerequisites
and prospective acceptance with the physical experiment owner before running
a baseline. No performance acceptance threshold is invented by this page.

## Reused primary interfaces and attribution

- [W3C Media Playback Quality](https://w3c.github.io/media-playback-quality/):
  `getVideoPlaybackQuality`, cumulative counters and reset semantics.
- [WICG video frame callback specification](https://wicg.github.io/video-rvfc/):
  `requestVideoFrameCallback`, compositor metadata and best-effort callbacks.
  This is a Community Group specification, not a W3C Recommendation.
- [aiohttp FileResponse](https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.FileResponse)
  and [its existing implementation](https://docs.aiohttp.org/en/stable/_modules/aiohttp/web_fileresponse.html):
  reuse the project's aiohttp dependency and its file/Range handling instead
  of implementing video streaming. aiohttp is Apache-2.0 licensed.
- [PresentMon 2.6.0](https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0),
  [console documentation](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/README-ConsoleApplication.md)
  and [MIT license](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/LICENSE.txt):
  external display-measurement reference; no PresentMon code is copied here.
- [Blender's official high-frame-rate clip directory](https://download.blender.org/demo/movies/BBB/)
  and [CC BY 3.0 sharing instructions](https://peach.blender.org/about/): one
  suitable source candidate is the Sunflower 1080p60 normal version. Preserve
  Blender Foundation and Janus Bager Kristensen credits with acquired assets.
  The movie is not bundled or downloaded by this tool.

Primary interfaces were reviewed on 1 November 2026. These new example sources
are original project code under Apache-2.0; no external implementation was
copied. Focused component checks run with
`python -m unittest discover -s tests -p test_video_coexistence.py -v`.
Those checks use synthetic counters and file bytes, not actual video playback.
