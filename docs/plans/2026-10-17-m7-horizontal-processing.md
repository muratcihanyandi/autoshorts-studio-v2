# M7 — Horizontal Video Processing Implementation Plan

> **For agents:** Execute task-by-task in this session per the workflow in
> `AGENTS.md` (test first, commit incrementally, record evidence in
> `docs/PROGRESS.md`). The repository and test results are the only source
> of truth.

**Goal:** Planned source videos pass through a durable, stage-gated
pipeline: authorized download -> integrity + ffprobe inspection ->
transcript -> silence/scene/energy analysis -> clip candidates with
similarity checks, all as M6 queue jobs with results in PostgreSQL.

**Architecture:** One `media_process` job per planned source video,
executed by the existing `JobWorker`. External tools (ffmpeg/ffprobe,
yt-dlp) run as subprocesses — probed on PATH, zero new Python
dependencies. Each stage is idempotent (`media_assets.stage` records the
last completed stage; a retried job resumes instead of redoing work).
Downloads serialize through a shared asyncio lock and honor the M6 token
bucket settings and disk guard.

**Tech Stack:** Python 3.11, SQLAlchemy 2 (sqlite tests / PostgreSQL
prod), Alembic, ffmpeg/ffprobe 8.x subprocess, yt-dlp subprocess
(optional at runtime, installed in the container image).

---

## Roadmap mapping (docs/ROADMAP.md M7)

| Roadmap task | Where |
|---|---|
| Authorized media-source adapters | `media_download.py` (protocol + LocalImport + YtDlp) |
| Sequential downloads | shared `asyncio.Lock` in `build_handlers`; one download at a time |
| Validate media integrity | `media_probe.py` (ffprobe parse + stream/duration checks + sha256) |
| Inspect metadata with ffprobe | `media_probe.py` -> `media_inspections` table |
| Transcript generation | `media_transcript.py` (VTT/SRT sidecar parse; yt-dlp writes auto-subs) |
| Intro/outro candidate detection | `media_analysis.py` (silencedetect leading/trailing runs) |
| Scene and reaction analysis | `media_analysis.py` (scene cuts + windowed audio RMS energy) |
| Clip-candidate generation | `clip_candidates.py` (scored, non-overlapping windows) |
| Content similarity checks | `clip_candidates.py` (word 3-gram Jaccard vs channel's prior candidates) |
| Store processing results in PostgreSQL | tables `media_assets`, `media_inspections`, `transcripts`, `clip_candidates` |

## Task 1: Config + models + migration 0007

**Files:** Modify `backend/app/config.py`, `backend/app/models.py`;
Create `backend/alembic/versions/0007_media_pipeline.py`;
Test `backend/tests/test_media_pipeline.py` (model part).

- Settings additions: `ffmpeg_bin="ffmpeg"`, `ffprobe_bin="ffprobe"`,
  `clip_min_seconds=20`, `clip_max_seconds=90`, `silence_noise_db=-35.0`,
  `silence_min_seconds=1.5`, `scene_threshold=0.4`,
  `planned_poll_interval_minutes=5`.
- Models (style: String + CheckConstraint, JSONColumn, tz timestamps):
  - `MediaAsset`: unique `source_video_id` FK, `origin`
    ('youtube'|'local_import'), `status`
    (downloading/downloaded/inspected/transcribed/analyzed/processed/failed),
    `stage` (download/inspect/transcript/analysis/candidates), file_path,
    file_bytes, sha256(64), `analysis` JSONB, last_error, timestamps.
  - `MediaInspection`: unique `media_asset_id` FK, duration_seconds,
    width, height, fps, video_codec, audio_codec, has_audio,
    format_name, `raw` JSONB, created_at.
  - `Transcript`: unique `media_asset_id` FK, language, source
    (sidecar/auto_caption), segment_count, `segments` JSONB
    (`[{start,end,text}]`), raw_path, created_at.
  - `ClipCandidate`: `source_video_id` FK, start/end/duration seconds
    (CheckConstraint end > start), score, reason, status
    (candidate/rejected/selected), duplicate_of_candidate_id (nullable
    int), `detail` JSONB, created_at, index on source_video_id.
- Migration 0007 mirrors 0006's structure (read it first). Offline SQL
  check: `alembic upgrade head --sql`.
- Tests: rows persist + unique constraints reject duplicates (sqlite,
  FK-enforcing pattern from `tests/conftest.py`).

## Task 2: media_probe service

**Files:** Create `backend/app/services/media_probe.py`;
Test `backend/tests/test_media_probe.py`.

- `run_ffprobe(ffprobe_bin, path) -> dict`: asyncio subprocess
  `ffprobe -v error -print_format json -show_format -show_streams`,
  `MediaProbeError` (Turkish message) on non-zero exit / bad JSON.
- `parse_probe(raw) -> InspectionData` dataclass: duration, width,
  height, fps (r_frame_rate "30000/1001" -> float), video_codec,
  audio_codec, has_audio, format_name.
- `integrity_ok(data) -> bool`: video stream present, duration > 0,
  width/height > 0.
- `sha256_file(path)`: chunked hash via `asyncio.to_thread`.
- Tests (real ffmpeg, on PATH per AGENTS.md): generate a small mp4 with
  lavfi sources; probe it, assert duration/width/has_audio; truncated
  file -> probe/integrity fails; sha256 stable + matches known size.

## Task 3: media_download service (adapters)

**Files:** Create `backend/app/services/media_download.py`;
Test `backend/tests/test_media_pipeline.py` (download part).

- `DownloadResult` dataclass (path, origin, file_bytes).
- `MediaSourceAdapter` Protocol: `async fetch(source_video_id, title,
  youtube_video_id, dest_dir) -> DownloadResult`.
- `LocalImportAdapter(import_path)`: copy2 via to_thread to
  `downloads/<source_video_id>.<ext>`; error when missing/empty; the
  operator's original file is never modified (acceptance: originals
  preserved).
- `YtDlpAdapter(settings, runner=None)`: command
  `[bin, "-f", "bv*+ba/b", "--merge-output-format", "mp4",
  "--write-auto-subs", "--sub-langs", "tr,en", "--no-playlist",
  ("-o", template), url]` + `--limit-rate {kbps}K` when
  `download_rate_limit_kbps > 0`; output template
  `downloads/<source_video_id>.%(ext)s`; runner injectable for tests;
  `shutil.which` probe -> clear Turkish error when the binary is absent.
- `download_lock` passed in by the caller (worker registry) — the
  adapter layer itself stays lock-free and testable.
- Tests: fake adapter writes bytes; local import copies (original
  intact, dest named by video id); yt-dlp command construction asserted
  with a recording fake runner (including rate-limit flag on/off);
  missing binary error.

## Task 4: media_transcript service

**Files:** Create `backend/app/services/media_transcript.py`;
Test `backend/tests/test_media_transcript.py`.

- Pure parsers: `parse_vtt(text)` (WEBVTT header, cue settings, arrow
  timestamps `00:00:01.000 --> 00:00:03.000`), `parse_srt(text)`
  (index lines, comma milliseconds). Both return
  `[{start, end, text}]`, skip malformed cues, merge nothing.
- `find_sidecar(media_path)`: same stem `.vtt`/`.srt` in the same dir.
- `transcript_text_in_range(segments, start, end)`: joined text of
  overlapping segments (for candidate scoring + similarity).
- Tests: crafted VTT/SRT strings incl. malformed cues; sidecar lookup;
  range extraction.

## Task 5: media_analysis service

**Files:** Create `backend/app/services/media_analysis.py`;
Test `backend/tests/test_media_analysis.py`.

- `detect_silence(ffmpeg_bin, path, noise_db, min_seconds)`: run
  `ffmpeg -i path -af silencedetect=... -f null -`; parse
  `silence_start:`/`silence_end:` pairs from stderr (pure parse helper
  + subprocess wrapper).
- `detect_scene_changes(ffmpeg_bin, path, threshold)`: run
  `ffmpeg -i path -vf "select='gt(scene,T)',showinfo" -f null -`; parse
  `pts_time:X` from showinfo lines.
- `audio_rms_windows(ffmpeg_bin, path, window_seconds=1.0)`: decode to
  mono 8kHz s16le on stdout pipe; windowed RMS in Python.
- `intro_outro_from_silences(silences, duration)`: leading run -> intro
  candidate, trailing run -> outro candidate (pure).
- Test media (one command, reused via helper in the test module):
  color cuts at 4s/8s (scene changes) + sine audio muted 0-2s and
  10-12s (silences), 320x240, 15fps, 12s.
- Tests: real ffmpeg on generated media; detected timestamps within
  +-0.5s tolerance; parse helpers against crafted log text.

## Task 6: clip_candidates service

**Files:** Create `backend/app/services/clip_candidates.py`;
Test `backend/tests/test_clip_candidates.py`.

- `generate_candidates(duration, intro_end, outro_start,
  scene_changes, energy_windows, segments, *, clip_min, clip_max,
  max_candidates=5) -> list[CandidateSpec]`: window lengths {min, mid,
  max}, 5s step; score = 0.4*norm(mean energy) + 0.3*norm(scene density)
  + 0.3*transcript coverage - 0.5*silence overlap fraction; greedy
  non-overlapping top-K by score; CandidateSpec(start, end, score,
  detail dict, reason).
- `word_ngram_jaccard(a, b, n=3)` and
  `is_near_duplicate(text, existing_texts, threshold=0.8)`: word
  3-gram Jaccard similarity (pure).
- Validation invariant everywhere: `0 <= start < end <= duration`
  (roadmap acceptance: candidate timestamps are valid).
- Tests: synthetic inputs produce valid, non-overlapping, ranked
  candidates; intro/outro excluded; near-duplicate detection (incl.
  exact copy -> True, unrelated text -> False).

## Task 7: media_pipeline orchestrator

**Files:** Create `backend/app/services/media_pipeline.py`;
Test `backend/tests/test_media_pipeline.py` (pipeline part).

- `MediaPipelineService(sessionmaker, settings, adapter_resolver)`:
  `async run(source_video_id, import_path=None) -> dict`.
  Stages (each gated on `media_assets.stage`, audit event per stage via
  existing `record_event`):
  1. guard: source channel authorized, video status 'planned' (or
     already 'processed' -> idempotent early return);
  2. download (shared lock + `JobService.disk_ok` guard) ->
     file_path/bytes;
  3. inspect: sha256 + ffprobe -> integrity; failure sets
     asset.status='failed' + last_error and raises (job retry resumes
     at the failed stage);
  4. transcript: sidecar parse -> Transcript row (or "none" outcome);
  5. analysis: silence/scene/energy -> asset.analysis JSONB;
  6. candidates: delete-then-insert rows for the video (idempotent),
     near-duplicates vs the channel's existing candidate texts get
     status='rejected' + duplicate_of_candidate_id;
  7. finalize: video -> 'processed', asset -> 'processed'.
- Tests (real ffmpeg synthetic media + LocalImportAdapter):
  - full pass: all four tables populated, video 'processed', candidate
    timestamps within duration, audit events recorded;
  - failure path: adapter error -> job fails, asset 'failed' with
    Turkish last_error, retry after fixing resumes (no duplicate rows);
  - re-run of a processed video changes nothing (idempotent).

## Task 8: worker wiring + deployment image

**Files:** Modify `backend/app/worker.py`, `backend/Dockerfile`,
`backend/requirements.txt`; Test additions in
`backend/tests/test_jobs.py` / `test_media_pipeline.py`.

- `build_handlers`: register `media_process` (payload
  `{"source_video_id": N, "import_path"?: str}`) with a shared
  `asyncio.Lock` for sequential downloads; effective settings inside
  the handler (site-managed values apply without restart).
- Worker loop: `enqueue_planned_jobs()` — interval-gated by
  `planned_poll_interval_minutes`, one `media_process` job per
  'planned' video, JobService dedupe prevents pileup.
- `requirements.txt`: add pinned `yt-dlp` (subprocess binary; not
  imported). Dockerfile: `apt-get install ffmpeg` in the root stage.
- Tests: worker enqueues media jobs for planned videos only; handler
  registered in build_handlers; full pipeline via
  `JobWorker.run_job` succeeds (real ffmpeg media).

## Task 9: docs + full verification

- `docs/DECISIONS.md`: ADR-012 (subprocess-isolated media tools,
  stage-gated idempotent pipeline, caption-sidecar transcripts,
  local-import adapter for authorized test media).
- Full suite: `cd backend && ./.venv/Scripts/python.exe -m pytest`
  (record exact counts), frontend untouched, secret scan
  `python tools/scan_secrets.py`.
- `docs/ROADMAP.md`: M7 status per evidence; `docs/PROGRESS.md`:
  M7 section + handoff notes update.
- Commits per task; final working tree clean.

## Acceptance audit (from ROADMAP)

| Criterion | Evidence |
|---|---|
| Authorized test media passes the entire pipeline | full-pipeline test with real ffmpeg media via LocalImportAdapter |
| Failures recorded and recoverable | failure-path test: asset 'failed' + last_error; retry resumes at stage |
| Candidate timestamps valid | invariant test `0 <= start < end <= duration` |
| Original files preserved while needed | local import copies (never moves); downloads stay in `downloads/`; tmp cleanup only touches `tmp/` |
| Worker within resource limits | sequential download lock, `max_concurrent_jobs`, disk guard before download, yt-dlp `--limit-rate` |
