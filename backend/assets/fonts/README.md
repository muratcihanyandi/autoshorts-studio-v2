# Burn-in caption fonts

Fonts burned into vertical clips by libass (see
`app/services/subtitle_style.py`). Copied into the Docker image at
`/usr/share/fonts/truetype/studio/` so renders are deterministic and
CI never downloads fonts at build time.

- `Anton-Regular.ttf` — Anton by Vernon Adams, Google Fonts
  (fonts.google.com/specimen/Anton), SIL Open Font License 1.1.
- `NotoSans-Regular.ttf` — Noto Sans by Google, SIL Open Font License
  1.1 (same file already self-hosted for the frontend brand kit).

DejaVu Sans (the "klasik", "shorts_sari" and "kutu" presets) ships with
the image via the `fonts-dejavu-core` apt package.
