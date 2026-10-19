# M8 — Vertical Studio and Webcam Detection Implementation Plan

> **For agents:** Execute task-by-task per `AGENTS.md` (TDD, commit per
> task, evidence in `docs/PROGRESS.md`). Repository and test results are
> the only source of truth.

**Goal:** Turn M7's clip candidates into validated 1080x1920 vertical
videos with a reliably detected webcam region, burned-in subtitles in
the right place, and a review path when detection is uncertain.

**Architecture:** A new `clip_render` job type on the M6 queue. Webcam
detection runs in-process with OpenCV (headless, Haar cascade shipped
with the wheel — no extra model files), sampling frames from the clip
window, clustering detections across frames, and scoring confidence.
Rendering composes the 9:16 layout (top webcam crop / bottom video
crop) with ffmpeg; a validator re-probes the output (resolution,
duration, A/V sync). Uncertain detection marks the render `review`
instead of failing. Per-source calibration (manual region or
confidence threshold) lives in a new table.

**Tech Stack:** opencv-python-headless==4.12.0.88 (aarch64 wheel
verified), numpy (pulled by opencv), ffmpeg subprocess (existing
pattern), migration 0008.

---

## Roadmap mapping

| Roadmap task | Where |
|---|---|
| 9:16 rendering templates | `vertical_render.py` (layout data + ffmpeg graph) |
| Multi-frame webcam detection | `webcam_detect.py` (frame sampling + per-frame detect) |
| Tracking and confidence scoring | `webcam_detect.py` (IoU clustering across samples) |
| Streamer-specific calibration | `webcam_calibrations` table + service |
| Manual region selection | calibration API + payload override |
| Top-webcam/bottom-video composition | `vertical_render.py` vstack layout |
| Subtitle positioning | bottom-section ASS burn-in, no webcam overlap |
| Generated-video validation | `vertical_render.py` validate_output (ffprobe) |
| Representative test videos | real public-domain face fixture + synthetic media |

## Task 1: Dependency + fixture groundwork

- requirements.txt += opencv-python-headless==4.12.0.88; install in dev
  venv; verify `cv2.data.haarcascades` ships the frontalface cascade.
- Find a small public-domain frontal-face image (NASA/Wikimedia);
  verify Haar detects it; commit under `backend/tests/assets/`.
- Build `make_face_video()` helper: turns the face image into a short
  mp4 (slight pan/jitter to exercise multi-frame tracking) with
  synthesized audio.

## Task 2: webcam_detect service

**Files:** Create `backend/app/services/webcam_detect.py`;
Test `backend/tests/test_webcam_detect.py`.

- `Detection` dataclass (x, y, w, h, frame_index).
- `FaceDetector` protocol; `HaarFaceDetector` (frontalface_alt2,
  grayscale + equalizeHist, configurable minNeighbors/scaleFactor).
- `sample_frames(video_path, start, end, fps=1.0)` -> frame array +
  timestamps (cv2.VideoCapture seek by ms).
- `cluster_detections(detections, iou_threshold)` -> clusters with
  detection_rate, median box, size jitter (pure, unit-testable).
- `detect_webcam_region(video, start, end, ...)` -> WebcamResult:
  region box, confidence, frames_sampled, faces_found; best cluster =
  highest (detection_rate, area).
- Tests: clustering math on synthetic boxes (stable cluster vs noise);
  real detection on the face-video fixture (region found, confidence
  high); no-face video (synthetic color video) -> no region, low
  confidence.

## Task 3: calibration + review semantics

**Files:** Create `backend/app/services/webcam_calibration.py`;
Modify models + migration 0008; tests.

- Table `webcam_calibrations`: source_channel_id unique FK, region
  (x,y,w,h ints), manual bool, min_confidence float, updated_at.
- `WebcamCalibrationService`: get/set per source; `resolve_region`:
  manual region wins outright; else detection must beat the calibrated
  (or default 0.5) confidence, else `review`.
- API: PUT /channels/{cid}/sources/{sid}/webcam-calibration +
  GET (manual region entry point; source routes pattern).
- clip_candidates stay untouched; review lands on rendered_clips.

## Task 4: vertical_render service

**Files:** Create `backend/app/services/vertical_render.py`;
Test `backend/tests/test_vertical_render.py`.

- `build_layout(source_w, source_h, webcam, out_w=1080, out_h=1920)`:
  top square-ish webcam crop (padded), bottom video center crop,
  subtitle band inside the bottom section (pure; validated no-overlap).
- `render_vertical(...)`: ffmpeg `-ss/-t` input, split, two crops,
  scale, vstack, x264 + aac, burn ASS subtitles (positioned bottom of
  the video section) via escaped filter path.
- `validate_output(path, expected_duration)`: ffprobe 1080x1920,
  duration within tolerance, has audio, video/audio stream durations
  within 0.25s (sync), subtitle burn present is a layout-guarantee.
- Tests: layout math (pure); real render on synthetic 12s media +
  face fixture; output probed 1080x1920, A/V synced; subtitle region
  does not overlap webcam (layout invariant + rendered probe).

## Task 5: clip_render pipeline + worker + schema

**Files:** Create `backend/app/services/vertical_pipeline.py`;
migration 0008 adds `rendered_clips` (clip_candidate_id unique FK,
file_path, bytes, w/h, duration, layout JSONB, validation JSONB,
status rendering/rendered/review/failed, last_error, timestamps);
Modify `backend/app/worker.py`.

- `clip_render` job (payload: clip_candidate_id): load candidate +
  asset + calibration -> detect/resolve webcam -> review short-circuit
  (rendered_clips.status='review' + audit `render.review`) -> render ->
  validate -> persist. Idempotent on re-run (unique candidate row,
  skip when already rendered).
- Worker: enqueue clip_render for status='candidate' rows
  (interval-gated, deduped, priority 8).
- Tests: e2e via JobWorker on the face fixture (rendered row with
  valid output file); uncertainty path via a forced low threshold
  (review row, no render); idempotent re-run; worker enqueue test.

## Task 6: docs + full verification

- ADR-013 (OpenCV in-process detection, Haar default + protocol for
  stronger detectors, calibration table, review semantics).
- Full backend suite + frontend + secret scan; ROADMAP/PROGRESS
  records; commit + push (CI builds the image with opencv).

## Acceptance audit

| Criterion | Evidence |
|---|---|
| Test clips render with expected layout | render test: probed 1080x1920, two-section layout |
| Webcam uncertainty triggers review | forced-threshold test: rendered_clips.status='review' |
| Audio and video remain synchronized | validate_output: stream durations within 0.25s |
| Cropping and subtitle overlap validated | layout invariant tests + rendered probe |
| Performance and detection limitations documented | ADR-013 + PROGRESS (sample fps, CPU notes) |
