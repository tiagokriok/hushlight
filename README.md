# Hushlight

Theme-native privacy indicators for the Omarchy top bar: microphone, camera,
and recording (screen plus system audio) capture, shown with distinct icons in
the live theme colors.

Hushlight is deliberately conservative. It reports what it can observe on
supported paths and says so; an absent indicator never proves that nothing is
recording.

## Contents

| Path | Purpose |
| --- | --- |
| `manifest.json` | Plugin manifest (`hushlight.privacy`, bar widget, right section) |
| `Widget.qml` | Compact bar widget; launches and validates the backend |
| `backend/main.py` | Backend entry point; streams newline-delimited JSON |
| `backend/pipewire.py` | `pw-dump` framing plus graph classification |
| `backend/camera.py` | Device-holder reconciliation and probe suppression |
| `backend/runtime.py` | Subprocess/event lifecycle and snapshot emission |
| `backend/status.py` | Status values and layering |
| `tests/` | `unittest` behavioral tests (no real capture) |

## Evidence semantics

Each indicator has one of three states:

- `active` - capture or device access was observed on a supported path.
- `unobserved` - nothing was observed on the supported paths. This is **not**
  proof of global inactivity.
- `unknown` - evidence was unavailable, incomplete, or unclassifiable.

Rules:

- Positive activity wins over a simultaneous coverage gap; the gap is kept in
  the status `limitations` list.
- Direct camera device access (`fuser` holders sustained past a debounce
  window) is reported as "Camera device accessed". It is **not** confirmed
  recording and never says "streaming".
- A status `limitations` list is always present and rendered by the widget.

The backend emits one complete snapshot per line:

```json
{"version":1,"microphone":Status,"camera":Status,"recording":Status}
```

where each `Status` is `{"state":..., "evidence":..., "limitations":[...]}`.
Snapshots contain no PIDs, window titles, raw device metadata, or capture
contents, and no captured string is ever executed.

## Coverage matrix

| Scenario | Status | How |
| --- | --- | --- |
| Microphone capture via PipeWire (incl. PulseAudio clients) | Supported | Running `Stream/Input/Audio` linked from an ALSA `Audio/Source` |
| System-audio / loopback capture | Supported (classification not live-validated) | `Stream/Input/Audio` linked from a `.monitor` source or `Audio/Sink` |
| Screen capture through the installed Hyprland portal | Supported (portal-specific) | Active portal-owned `Video/Source` linked to a `Stream/Input/Video`; other portals/compositors are unverified |
| Camera capture through PipeWire | Limited to `device.api: v4l2` | Running `Video/Source` with `device.api: v4l2` linked to a video input; libcamera and unclassified video sources are not attributed and fall back to `unknown` |
| Direct V4L2 camera access without PipeWire | Partial (access only) | `fuser` holders sustained past 0.75 s; never claimed as streaming |
| Playback / hardware presence / suspended devices | Not a capture signal | Ignored by design |
| Internal browser-tab capture (e.g. a shared tab in Brave) | Unsupported | No PipeWire stream is visible; requires browser integration |
| Non-portal screen capture | Possibly invisible | Only portal-owned video sources are classified as screen capture |
| Other users / restricted processes | Not observable | An unprivileged observer cannot see their holders |
| Ambiguous or virtual routing | Reported `unknown` | Never guessed as microphone |

## UI

- Distinct glyphs per active type, so meaning never relies on color alone.
  Glyphs are built with `String.fromCodePoint`, which handles the
  supplementary-plane Nerd Font codepoints correctly.
- Colors bind to the live theme (`Color.bar.text`, `Color.bar.active`); no
  hardcoded status palette, and theme switches apply while running.
- Icons are laid out in a grid: one row when horizontal, one column when the
  bar is vertical, sized for three simultaneous indicators.
- A compact coverage marker (shield, or question glyph when unknown) is shown
  when no active type is visible so the tooltip stays discoverable.
- The one-line tooltip surfaces each indicator's evidence (for example
  "Camera device accessed"), renders `unobserved` as "not observed" rather
  than "idle", and appends the deduplicated limitations so coverage gaps
  remain visible.
- No click actions and no popup; accessible name and description are set.

## Process model

The widget launches one backend process per widget instance, and the bar
exists once per monitor, so a multi-monitor setup runs one backend per
monitor. Each backend owns a `pw-dump` and an `inotifywait` child. This is
intentional: a shared singleton was out of scope, and the per-monitor cost is
small (event-driven reads plus one `fuser` reconcile per second at most).

Owned children set `PR_SET_PDEATHSIG` to `SIGTERM`, so if the backend is
killed with `SIGKILL` or the widget is unloaded, its `pw-dump`/`inotifywait`
children are terminated by the kernel instead of being orphaned. Normal
teardown additionally kills the child process group and reaps it.

## Validation performed

All commands were run from the repository root; nothing was installed or
enabled, and no desktop configuration was changed.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q backend tests
python3 -m trace --count --summary --missing \
  --coverdir /tmp/opencode/hushlight-coverage --ignore-dir /usr/lib \
  --module unittest discover -s tests
omarchy plugin validate .
qmllint -I <qs-import-dir> -I /usr/lib/qt6/qml Widget.qml
```

Actual results:

- `unittest`: 77 tests, all passing. Includes a real-subprocess test that
  SIGKILLs an isolated backend parent and proves its owned child exits.
- `compileall`: clean.
- `trace`: backend line coverage 94% (camera 100%, pipewire 91.5%,
  runtime 94.9%, status 97.8%). `backend/main.py` is the entry point and is
  exercised by the live smoke run rather than the unit suite.
- `omarchy plugin validate .`: exit 0.
- `qmllint`: exit 0, no diagnostics, with `qs.Commons`/`qs.Ui` resolved through
  a `qs` import path plus the installed Quickshell modules.
- Live smoke: `python3 backend/main.py` ran for 4 s with read-only interfaces,
  emitted `unknown` then `unobserved` snapshots, and on SIGTERM left no
  `pw-dump`/`inotifywait` children behind.

`qmlformat` parsed `Widget.qml` successfully (exit 0), but this build has no
`--normalize` flag and reformats to four-space indentation, which does not
match the installed widgets. The file therefore keeps the house two-space
style.

## Manual install (not performed)

Installation requires separate approval and was not done.

1. Copy this directory to
   `~/.config/omarchy/plugins/hushlight.privacy/` (include `backend/` and
   `Widget.qml`).
2. `omarchy-shell shell rescanPlugins`
3. `omarchy plugin enable hushlight.privacy`
4. `omarchy bar move hushlight.privacy --section right`

The widget starts disabled until enabled, and its backend runs as
`python3 <plugin>/backend/main.py`. Python 3 is required on `PATH`.

## Known limitations

- macOS-equivalent security guarantees are not provided; only the paths above
  are observed.
- Camera attribution is limited to `device.api: v4l2` and the installed
  Hyprland portal. libcamera and other video sources are reported as `unknown`
  rather than guessed.
- System-audio loopback classification and camera `v4l2` capture need
  representative live validation.
- Concurrent sessions, crashed applications, and plugin unload in the real
  shell remain to be verified live.
