# Character / Multi-Platform Source System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: execute task-by-task; three workstreams
> (A backend-core, B pipeline, C frontend) run as parallel subagents after
> Task 0 (shared schema) lands. Integration owner: the main session.

**Goal:** Streamers become first-class "characters" (photo, per-character AI
prompt, YouTube/Twitch/Kick sources); reaction sources render trimmed
horizontal (no subtitles) + vertical shorts (subtitles); AI metadata gains a
global/character system-prompt chain with title, hook, thumbnail text,
description, tags; webcam detection validates against the character's photo.

**Architecture:** One new `characters` table binds N source channels.
`source_channels` gains platform/ref/reaction/trim columns. Rendering gains
an `orientation` dimension (vertical shorts stay subtitle-burned; horizontal
full cuts never burn subtitles). The LLM metadata prompt resolves
character prompt → global prompt → built-in default. Webcam regions are
validated against the character's stored reference face; uncertain matches
route to the existing review path.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic (backend), React + TS +
Vite (frontend), OpenCV + ffmpeg (matching/rendering), pytest + Vitest.

**Rights guardrail (non-negotiable):** sources only process after
`permission_status = authorized`. Non-reaction sources render vertical
shorts ONLY (the stated usage rule for streamer content). Reaction sources
additionally produce one trimmed horizontal cut. No detection-evasion
features; the protection is the rights record plus transformative output.

---

## Shared contracts (implemented in Task 0 by the main session)

### Models (`backend/app/models.py`)

```python
class Character(Base):
    """A streamer/person tracked by the studio (M13)."""
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Relative path under MEDIA_ROOT, e.g. characters/7_ab12cd3f.jpg
    photo_path: Mapped[str | None] = mapped_column(String(255))
    # Cropped reference face (characters/7_ref.png); None until photo upload
    reference_face_path: Mapped[str | None] = mapped_column(String(255))
    system_prompt: Mapped[str | None] = mapped_column(Text)  # None -> global
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

`SourceChannel` additions (single platform key — `youtube_channel_id`
keeps its name but carries the platform key for every platform: UC id
for YouTube, channel URL/name for Twitch/Kick):
- `platform: str(16)` default `"youtube"`, CheckConstraint in
  `('youtube','twitch','kick')`
- `character_id: FK characters.id ON DELETE SET NULL, nullable`
- `reaction_source: bool default False`
- `trim_start_seconds: float default 0`, `trim_end_seconds: float default 0`

`RenderedClip` additions:
- `orientation: str(12)` default `"vertical"`, CheckConstraint in
  `('vertical','horizontal')`
- `source_video_id: FK source_videos.id ON DELETE CASCADE, nullable`
  (horizontal full cuts have NULL `clip_candidate_id`)
- `thumbnail_path: str(255) | None`
- Unique `(clip_candidate_id, orientation)` replaces the old single-column
  unique (NULL candidate rows are exempt in both SQLite and PG).

`ClipMetadata` additions: `hook: str` default `""` (<=120),
`thumbnail_text: str` default `""` (<=80); `clip_candidate_id` becomes
nullable and a `source_video_id` FK is added — horizontal full cuts
carry their metadata with a NULL candidate (code-guarded to one
revision chain per source video). Thumbnails are stored on
`rendered_clips.thumbnail_path` and composed when metadata is approved.

`PublishedVideo` additions: `orientation: str(12)` default `"vertical"`;
unique becomes `(clip_candidate_id, orientation)`.

`Settings` (`backend/app/config.py`):
`metadata_system_prompt: str = ""`.

### Migration

`backend/alembic/versions/0011_characters_orientation.py` — creates
`characters`; adds all columns above; drops
`uq_rendered_clips_clip_candidate_id` / the old published_videos unique and
creates the composite ones. Follow the style of `0010_*.py`.

### API surface (workstream A implements)

- `GET  /api/characters` → `{characters:[...], total}`
- `POST /api/characters` `{name, system_prompt?, notes?}` → 201
- `GET/PATCH/DELETE /api/characters/{id}` (PATCH: name/system_prompt/notes;
  blank system_prompt clears it)
- `POST /api/characters/{id}/photo` multipart `file` → validates image
  (cv2.imdecode, <=8MB, jpg/png/webp), stores under
  `{MEDIA_ROOT}/characters/{id}_{sha8}.{ext}`, extracts reference face via
  the existing Haar detector (largest face, 20% padding) to
  `characters/{id}_ref.png`; no face → reference stays NULL (whole-image
  fallback). Returns `{photo_path, reference_face: bool}`.
- `GET /api/characters/{id}/photo` → FileResponse (404 when unset).
- `POST /api/channels/{channel_id}/sources` extended body:
  `{youtube_channel_id (platform key: UC id for youtube, channel URL
  for twitch/kick), platform, title, character_id?, reaction_source?,
  trim_start_seconds?, trim_end_seconds?, filter_rules?}`
- `PATCH /api/sources/{id}` accepts the new fields.
- `GET /api/channels/{id}/sources` returns them (plus `character_name`).
- `POST /api/sources/{source_id}/videos` `{url, title}` — manual VOD import
  for twitch/kick: creates a deduped `SourceVideo`
  (`youtube_video_id` = video key from URL), enqueues `media_process` with
  `import_path=url` (same payload shape as
  `tests/test_media_pipeline.py:874`). YouTube sources keep using
  `POST /api/channels/{id}/discover` (non-youtube sources are skipped with
  a per-source note in the result).
- Settings: `metadata_system_prompt` becomes an editable plain field
  (SettingsUpdate/SettingsOut/EDITABLE_FIELDS).

## File ownership matrix (no cross-edits)

| Workstream | Owns |
|---|---|
| 0 (main) | `app/models.py`, `alembic/versions/0011_*`, `app/config.py` |
| A | `app/schemas_characters.py` (new), `app/services/character_service.py` (new), `app/api/routes/characters.py` (new), `app/main.py` router include, `app/schemas_sources.py`, `app/services/source_service.py`, `app/repositories/sources.py`, `app/api/routes/sources.py`, `app/services/settings_service.py` + `app/schemas_settings.py`, `tests/test_characters.py` (new), `tests/test_sources.py`, `tests/test_settings.py` |
| B | `app/services/vertical_render.py`, `app/services/vertical_pipeline.py`, `app/services/metadata_service.py`, `app/services/webcam_detect.py`, `app/services/character_match.py` (new), `app/services/thumbnail.py` (new), `app/services/publishing_service.py`, `app/services/planning_service.py`, `app/schemas_sources.py` metadata schema if needed, `tests/test_vertical_render.py`, `tests/test_vertical_pipeline.py`, `tests/test_metadata.py`, `tests/test_webcam_detect.py`, `tests/test_publishing.py`, `tests/test_character_match.py` (new), `tests/test_thumbnail.py` (new) |
| C | `frontend/src/api/characters.ts` (new), `frontend/src/screens/CharactersScreen.tsx` (new) + `.test.tsx`, `frontend/src/api/settings.ts` + `screens/SettingsScreen.tsx` (prompt field), `frontend/src/components/AppShell.tsx`, `frontend/src/App.tsx`, `frontend/src/screens/GuideScreen.tsx`, `frontend/src/styles/components.css` |

Shared files touched by exactly one workstream each (models.py/config.py
frozen after Task 0). `app/main.py` only by A. If a change outside the
matrix is unavoidable, the agent MUST leave a `# TODO(integration):` note
instead of editing.

---

## Task 0 (main session): schema + migration

1. Apply the model/config changes above.
2. Write migration `0011` (match `0010` style; verify `alembic upgrade head`
   on a scratch sqlite via the test suite).
3. Run `pytest -q` — existing 248 tests must pass (additive columns with
   defaults must not break anything).
4. Commit: `M13: character/orientation schema and migration`.

## Workstream A tasks (subagent, TDD)

A1. `schemas_characters.py` (CharacterCreate/Update/Out with
    `photo: {configured: bool}`-style masked view — never raw paths to
    clients? Return relative paths; the photo endpoint serves bytes).
A2. `character_service.py` CRUD (unique-name 409, Fernet not needed) +
    `routes/characters.py` + `main.py` include. Tests: create/list/patch/
    delete + 409 duplicate + 404.
A3. Photo upload/serve endpoints (contract above). Tests: valid png
    (use `cv2` to synthesize), oversized rejection, non-image rejection,
    reference-face extraction on the committed PD face fixture
    (`tests/fixtures` — see `test_webcam_detect.py` for the path), GET
    serves bytes.
A4. Sources extension (create/patch/list + manual VOD endpoint + discover
    skip note). Tests: twitch source requires platform_ref; youtube still
    requires channel id; character binding + reaction/trim round-trip;
    manual VOD creates deduped SourceVideo + media_process job (inspect
    jobs table); duplicate VOD 409.
A5. Settings `metadata_system_prompt` (plain, editable, empty allowed).
    Tests: set/read/patch/clear.
Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q` (all green).
Commit per task.

## Workstream B tasks (subagent, TDD)

B1. `character_match.py`: `extract_reference(photo_bgr) -> (ref_bgr|None)`;
    `similarity(region_bgr, ref_bgr) -> float` (HSV histogram correlation
    blended with normalized ORB matches); `search_region(frame_bgr,
    ref_bgr) -> (x,y,w,h,score)|None` (multi-scale `cv2.matchTemplate`,
    best window padded 10%). Tests with synthetic images (two crops of the
    same synthetic "face" score high; unrelated noise scores low).
B2. Webcam integration: when the source's character has a reference face,
    validate the detected webcam region with `similarity`; below the
    source's calibration threshold (default 0.30) → `search_region`
    fallback; still below → existing `review` status. No character →
    behavior unchanged. Tests extend `test_webcam_detect.py` with the PD
    face fixture as both photo and frame.
B3. Horizontal render in `vertical_render.py` (or a sibling function):
    1920x1080, input seek `-ss trim_start -to duration-trim_end` from the
    source config, NO subtitle burn, audio kept. Output validation
    (1920x1080, A/V streams). `vertical_pipeline.py`: reaction sources
    enqueue BOTH orientations (horizontal full cut: `clip_candidate_id`
    NULL, `source_video_id` set; code-guard idempotency); non-reaction
    sources enqueue vertical only (hard guard). Tests with real ffmpeg
    fixtures following `test_vertical_render.py` patterns.
B4. `thumbnail.py`: `compose(video_path, text, out_path)` — pick the
    sharpest of frames at 25/50/75% (Laplacian variance), scale to
    1280x720, draw `text` with the DejaVu font shipped in the image
    (find its path from `test_vertical_render.py` usage), save jpg.
    Called when metadata is approved (extend the approve route/service in
    `publishing.py`/`metadata_service`), stores `thumbnail_path` on the
    ClipMetadata row. Tests: real render produces a valid 1280x720 jpg
    with expected file size.
B5. Metadata prompt chain: resolve system prompt
    `character.system_prompt` (via candidate → source → character) →
    `settings.metadata_system_prompt` → built-in default Turkish prompt.
    LLM output schema extended with `hook`, `thumbnail_text` (validated
    lengths; ClipMetadata columns from Task 0). Tests with mocked LLM
    transport (follow `test_metadata.py`): character prompt reaches the
    transport; fallback to global; fallback to default.
B6. Publishing per orientation: guard `(clip_candidate_id, orientation)`
    and horizontal full cuts (one per source_video); horizontal publish
    carries its own metadata (thumbnail optional). Extend
    `test_publishing.py` with a both-orientation publish case.
Run: full backend suite green. Commit per task.

## Workstream C tasks (subagent, TDD)

C1. `api/characters.ts`: fetch/create/update/delete characters, photo
    upload (FormData), sources-under-character helpers
    (add source, list, authorize/revoke via existing PATCH, discover,
    manual VOD).
C2. `CharactersScreen.tsx`: character cards (photo thumb via
    `/api/characters/{id}/photo`, name, sources with platform badges,
    authorized/pending pills); add/edit form (name, photo file input,
    system_prompt textarea with "boş = genel prompt" help, notes);
    per-character "Kaynak Ekle" form (platform select; youtube → UC id,
    twitch/kick → URL; reaction checkbox; trim seconds); authorize/revoke
    buttons; "Keşfet" (youtube) / "VOD Ekle" (twitch/kick) actions.
    Follow `LlmProvidersScreen` edit-mode patterns.
C3. Nav + route: `karakterler` after `kanallar` in `AppShell.tsx`/`App.tsx`.
C4. SettingsScreen: "Metaveri Sistem Promptu (Genel)" textarea (plain
    field, `metadata_system_prompt`) with help text.
C5. GuideScreen: new section 3 "Karakter ve Kaynak Ekleme" (flow: karakter
    ekle → platform kaynakları ekle → izin ver → keşif/VOD → üretim;
    reaction vs normal davranış ve altyazı kuralı tablosu) +
    troubleshooting rows.
Tests: `CharactersScreen.test.tsx` (render, add character form, source
badge display) following `SettingsScreen.test.tsx` fetch-mock patterns;
update `App.test.tsx` if the nav assertion needs the new item.
Run: `npx tsc -b && npx vitest run && npx oxlint` (0 errors). Commit per
task.

## Integration (main session)

1. Full backend + frontend suites; fix conflicts (models.py/config.py are
   frozen after Task 0 — agents must not edit them).
2. Secret scan: `python tools/scan_secrets.py`.
3. Update `docs/PROGRESS.md` (section 3 + 7 + handoff notes) and this
   roadmap pointer; `docs/ROADMAP.md` M13 entry.
4. Commit `M13: characters, multi-platform sources, dual-orientation
   reaction rendering, prompt chain, webcam photo matching` and push.
5. Pi note: migration 0011 runs automatically on container start
   (`alembic upgrade head`); restart CasaOS app after image build.
