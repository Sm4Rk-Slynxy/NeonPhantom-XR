# NeonPhantom XR API

REST: `http://127.0.0.1:8321/api` · WebSocket: `/ws` on the same host.

- `GET /library`: cards `{id, file, name, thumb, duration_s, has_alpha, matted, available}`.
- `POST /import`: `{path: "/absolute/video.mov", mode: "auto", quality: "detailed"}` → `{job_id}`. Optional `init_path` and ordered `segments` array contain existing absolute paths.
- `POST /upload?mode=auto`: multipart `file` → `{job_id}`. Streams up to 2 GiB to disk. With `segments=true`, send optional multipart `init` and multiple `file` parts in chronological order; these become one job.
- AI quality: `detailed` (default) or `fast`; add `quality=fast` to upload queries or `quality` to import/retry JSON. Fast affects AI only and preserves full duration.
- Modes: `auto`, `ai`, `green`, `blue`, `alpha`, `keep`. Defaults to `auto`.
- `GET /jobs`: `{job_id, state, progress, input, name, mode, uploaded, phase, error, card_id?, init_path, segments, can_retry}`.
- `POST /jobs/:id/retry`: `{mode?: "auto"}` retries a failed job with retained sources.
- `DELETE /jobs/:id`: removes a finished job and any retained uploaded sources; converted cards remain.
- `GET /health`: `{tools: {ffmpeg, ffprobe, mpv}, features: {m4s_segments, retry_imports, fast_ai}, desktop_session}`.
- `GET /stage`: `{playing, card_id, height_px, corner}`.
- `POST /stage/play`: `{card_id}`. Non-success and a JSON `error` when launch fails.
- `POST /stage/stop`: closes the owned player and cancels shuffle.
- `POST /stage/geometry`: `{height_px: 480, corner: "br"}`. Height 160–1600; corners `br`, `bl`, `tr`, `tl`.
- `POST /stage/shuffle`: `{playlist?: name, card_ids?: [id]}`. Explicit IDs win; otherwise playlist or all cards. Plays one sequence, then stops.
- `GET /playlists`: `[{name, cards: [id]}]`.
- `POST /playlists`: `{name}`.
- `POST /playlists/:name/add`: `{card_id}` (deduplicated).
- `DELETE /playlists/:name`.
- `GET /favorites`: `[id]`.
- `POST /favorites`: `{card_id}` toggles favorite → `{favorited}`.
- `DELETE /cards/:id`: removes converted media, thumbnail, and references.

WebSocket events:

- `hello`.
- `job_progress`: `{job_id, progress, state, phase? , error?}`. State is `queued|running|done|error`; progress represents processing phases, not a time estimate.
- `job_done`: `{job_id, card_id}`. Refresh library/jobs after completion.
- `card_deleted`: `{card_id}`.
- `stage_state`: `{playing, card_id}`.
- `stage_error`: `{error}` (asynchronous shuffle failure).

The server also serves the frontend at `/` and media at `/media`. Run from the active desktop session for overlay playback. Persistent state is compatible with existing cards/jobs; newly added fields have defaults.


## Cutout engine upgrade

`GET /api/models` returns `{id,label,installed,experimental,installable}` entries.
`POST /api/models/:id/install` with `{}` queues an installation and returns `job_id`.
Installs share the serial import queue; progress/errors use the existing jobs API
and websocket protocol. Successful installs emit `models_changed`; no card is created.

Both JSON `/api/import` and multipart `/api/upload` query options accept:

- `model`: `legacy` (default), `matanyone2`, `wevisone-2b`, `wevisone-4b`.
- `subject`: 1–200 characters, default `person`, used by WeVisOne.
- `subject_box`: optional normalized `[x1,y1,x2,y2]`, used to restrict MatAnyone's seed.
  Multipart query values encode the array as JSON, e.g. `[0.1,0,0.9,1]`.
- `preview_seconds`: optional integer 1–10 for complete videos. Omit for full duration.
  Preview cannot be combined with fragmented M4S input.

Retries accept optional `model`, `subject`, and `subject_box`; otherwise they preserve
the original choices. Jobs retain engine/subject/region/preview settings. New cards
include `model` (empty for conversions without AI) and `preview` (boolean).
Existing state loads with Classic and full-duration defaults.

Windows health reports `platform: windows` and `desktop_player` availability instead
of mpv. The player uses authenticated loopback control on `DESKDANCE_PORT + 1`.
