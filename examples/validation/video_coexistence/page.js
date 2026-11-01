// SPDX-License-Identifier: Apache-2.0
// Native API observations; callback delays are not physical playback stalls.
'use strict';
const video = document.getElementById('video');
const startButton = document.getElementById('start');
const stopButton = document.getElementById('stop');
const status = document.getElementById('status');
let config, phase = 'idle', timer, sampler, callbackId;
let warmupStart, measurementStart, lastCallback;
let events = [], samples = [], truncated = false;
let callbacks = {count: 0, max_callback_gap_ms: 0, skipped_callback_frames: 0};

function settings() {
  const rect = video.getBoundingClientRect();
  return {user_agent: navigator.userAgent, performance_time_origin_ms: performance.timeOrigin,
    viewport: [innerWidth, innerHeight],
    screen: [screen.width, screen.height], device_pixel_ratio: devicePixelRatio,
    video_element: [rect.width, rect.height], video_pixels: [video.videoWidth, video.videoHeight],
    duration_s: video.duration, playback_rate: video.playbackRate, muted: video.muted,
    volume: video.volume, visibility: document.visibilityState,
    fullscreen: Boolean(document.fullscreenElement)};
}

function quality() {
  const q = video.getVideoPlaybackQuality();
  return {at_ms: performance.now(), media_time_s: video.currentTime,
    totalVideoFrames: q.totalVideoFrames, droppedVideoFrames: q.droppedVideoFrames,
    quality_creation_time_ms: q.creationTime, ready_state: video.readyState,
    paused: video.paused, playback_rate: video.playbackRate};
}

function append(list, item, limit) {
  if (list.length < limit) list.push(item); else truncated = true;
}

function event(name) {
  if (phase === 'idle' || phase === 'finished') return;
  append(events, {name, phase, at_ms: performance.now(), media_time_s: video.currentTime,
    ready_state: video.readyState, paused: video.paused}, config.max_events);
}

async function post(path, body, keepalive = false) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body), keepalive});
  if (!response.ok) throw new Error(`Saving failed (${response.status})`);
  return response.json();
}

function frame(now, metadata) {
  if (phase !== 'warmup' && phase !== 'measuring') return;
  if (phase === 'measuring') {
    callbacks.count++;
    if (lastCallback) {
      callbacks.max_callback_gap_ms = Math.max(callbacks.max_callback_gap_ms, now-lastCallback.at_ms);
      callbacks.skipped_callback_frames += Math.max(0, metadata.presentedFrames-lastCallback.presented_frames-1);
    }
    lastCallback = {at_ms: now, media_time_s: metadata.mediaTime,
      presented_frames: metadata.presentedFrames, presentation_time_ms: metadata.presentationTime,
      expected_display_time_ms: metadata.expectedDisplayTime};
  }
  callbackId = video.requestVideoFrameCallback(frame);
}

async function finish(outcome, reason, leaving = false) {
  if (phase === 'idle' || phase === 'finished') return;
  const priorPhase = phase;
  phase = 'finished';
  clearTimeout(timer); clearInterval(sampler);
  if (callbackId !== undefined) video.cancelVideoFrameCallback(callbackId);
  let end = null;
  try { if (measurementStart) end = quality(); } catch (_) { outcome = 'error'; reason = 'quality_read_failed'; }
  const report = {outcome, reason, last_phase: priorPhase,
    warmup_elapsed_ms: measurementStart ? measurementStart.at_ms-warmupStart : null,
    measurement_start: measurementStart || null, measurement_end: end,
    callback_observations: {...callbacks, last: lastCallback || null,
      interpretation: 'Callback delivery observations, not physical stalls or a dropped-frame counter'},
    events, samples, observations_truncated: truncated, settings_end: settings()};
  stopButton.disabled = true;
  video.pause();
  status.textContent = 'Saving the observation…';
  try {
    const summary = await post('finish', report, leaving);
    status.textContent = summary.outcome === 'completed'
      ? `Measurement saved. ${summary.frames.dropped_frames} of ${summary.frames.total_frames} frames dropped (${(summary.frames.dropped_fraction*100).toFixed(3)}%).`
      : `Saved ${summary.outcome}: ${summary.reason}. Use a fresh run to try again.`;
  } catch (error) {
    status.textContent = `${error.message}. The server's saved run remains incomplete; keep this page open.`;
  }
}

function beginMeasurement() {
  if (phase !== 'warmup') return;
  phase = 'measuring';
  measurementStart = quality();
  callbacks = {count: 0, max_callback_gap_ms: 0, skipped_callback_frames: 0};
  lastCallback = undefined;
  event('measurement_started');
  timer = setTimeout(() => finish('completed', 'window_elapsed'), config.measurement_s*1000);
}

startButton.addEventListener('click', async click => {
  if (phase !== 'idle' || !click.isTrusted) return;
  phase = 'starting'; startButton.disabled = true; stopButton.disabled = false;
  try {
    if (document.hidden || video.duration < config.warmup_s+config.measurement_s)
      throw new Error('The visible clip must contain the complete measurement window');
    video.currentTime = 0; video.playbackRate = 1;
    // Invoke play inside the trusted click, before awaiting network work.
    const playback = video.play();
    await Promise.all([playback, post('start', {trusted_start_click: click.isTrusted,
      clicked_utc: new Date().toISOString(), settings: settings()})]);
    if (phase === 'finished') { video.pause(); return; }
    phase = 'warmup'; warmupStart = performance.now(); event('warmup_started');
    callbackId = video.requestVideoFrameCallback(frame);
    timer = setTimeout(beginMeasurement, config.warmup_s*1000);
    sampler = setInterval(() => {
      if (phase !== 'warmup' && phase !== 'measuring') return;
      append(samples, {...quality(), phase, callback: lastCallback || null}, config.max_samples);
      const elapsed = (performance.now()-(measurementStart ? measurementStart.at_ms : warmupStart))/1000;
      status.textContent = `${phase === 'warmup' ? 'Warming up' : 'Measuring'}: ${Math.floor(elapsed)} / ${measurementStart ? config.measurement_s : config.warmup_s} seconds`;
    }, 1000);
  } catch (error) {
    await finish('error', error.message);
  }
});

stopButton.addEventListener('click', () => finish('incomplete', 'manual_stop'));
for (const name of ['playing', 'waiting', 'stalled', 'pause', 'seeking', 'seeked', 'ended', 'ratechange', 'error']) {
  video.addEventListener(name, () => {
    event(name);
    if (name === 'error' && phase === 'idle') {
      startButton.disabled = true;
      status.textContent = `The selected video could not load (media error ${video.error?.code || 'unknown'}).`;
    }
    if (phase !== 'warmup' && phase !== 'measuring') return;
    if (name === 'error') finish('error', `media_error_${video.error?.code || 'unknown'}`);
    else if (['pause', 'seeking', 'ended', 'ratechange'].includes(name)) finish('incomplete', name);
  });
}
document.addEventListener('visibilitychange', () => {
  event('visibility_'+document.visibilityState);
  if (document.hidden) finish('incomplete', 'page_hidden', true);
});
window.addEventListener('pagehide', () => finish('incomplete', 'page_closed', true));

async function initialize() {
  config = await (await fetch('config')).json();
  document.getElementById('clip').textContent = `${config.clip_name} · ${config.condition}`;
  if (!video.getVideoPlaybackQuality || !video.requestVideoFrameCallback) {
    status.textContent = 'This browser does not provide the required video observation APIs.';
    return;
  }
  const ready = () => { startButton.disabled = false; status.textContent = 'Ready. Click Start measurement when the setup is ready.'; };
  if (video.readyState >= 1) ready(); else video.addEventListener('loadedmetadata', ready, {once: true});
}
initialize().catch(error => { status.textContent = `Setup error: ${error.message}`; });
