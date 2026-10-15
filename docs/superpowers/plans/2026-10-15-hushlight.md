# Hushlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved theme-native privacy widget without installing it or modifying the live desktop.

**Architecture:** A QML bar widget consumes newline-delimited JSON from one Python backend. The backend watches PipeWire changes and camera-device access, emits conservative state snapshots, and owns all subprocess cleanup. Camera access and confirmed capture are distinct evidence levels.

**Tech Stack:** Installed QML/Quickshell, Python standard library, `pw-dump`, `inotifywait`, `fuser`, and standard-library `unittest`/`trace`.

**Spec:** Approved scope in conversation; `HANDOFF.md` and `docs/capture-research.md` supply requirements, observations, and limitations.

## Global Constraints

- No dependencies, privileged helpers, browser extensions, settings system, or popup.
- No install, enable, live desktop edits, commits, or publication without separate approval.
- Preserve existing untracked documentation. Repository has an unborn `main`; create a feature branch before product changes, without committing.
- Plugin ID: `hushlight.privacy`; manifest version `0.1.0`, schema version `1`, kind `bar-widget`, right section, no multiple instances per bar configuration.
- Theme bindings use installed `qs.Commons.Color` surface roles; no hardcoded status palette.
- Distinct microphone, camera, and recording icons with accessible names and tooltips; no distinction by color alone.
- State snapshot: `{"version":1,"microphone":Status,"camera":Status,"recording":Status}`. Each `Status` contains `state` (`active`, `unobserved`, or `unknown`), `evidence` (plain text), and `limitations` (list of plain strings).
- `unobserved` means no activity observed within supported paths, never global privacy. `unknown` means unavailable, incomplete, or unclassifiable evidence. Positive activity wins over a simultaneous coverage gap; preserve limitations.
- Direct-camera evidence must say `Camera device accessed`, not confirmed recording. Internal browser-tab capture remains unsupported.
- Backend output includes no PID, titles, raw device metadata, or capture contents. Do not execute strings derived from capture metadata.
- Files normally under 400 lines; 800 absolute maximum. Prefer immutable state transformations.

## Review Focus

1. Stream removal, ID reuse, and reconnect must not retain stale active state.
2. Playback, hardware presence, and brief camera probes must not become capture alerts.
3. Device hotplug, invisible holders, and missing tools must not become claims of global inactivity.
4. Simultaneous streams must remain active until the last relevant stream ends.
5. Unload, malformed output, and backend failure must terminate owned children and show unknown state.

## Files and interfaces

- `manifest.json`, `Widget.qml`: installable plugin entry point and compact UI.
- `backend/main.py`: executable Python entry point and line-oriented output.
- `backend/pipewire.py`: JSON-array framing, object snapshots, graph classification.
- `backend/camera.py`: bounded device-holder reconciliation and probe suppression.
- `backend/runtime.py`: subprocess/event lifecycle and JSON emission.
- `tests/test_pipewire.py`, `tests/test_camera.py`, `tests/test_runtime.py`: behavioral fixtures and fake subprocesses.
- `README.md`: usage, evidence semantics, coverage matrix, validation and manual install instructions only.

### Task 1: PipeWire classifier

**Interfaces:** `decode_updates(buffer: str) -> tuple[list[list[dict]], str]`; `apply_updates(objects: dict, updates: list[dict]) -> dict`; `classify(objects: dict, available: bool) -> dict` returning microphone, camera, and recording statuses.

- [x] Write failing unit tests with synthetic node/client/port/link fixtures. Assert playback-only and suspended hardware are unobserved; running audio capture linked to ALSA source is microphone active; sink-monitor capture is recording active, not microphone; portal-owned active video source linked to a video input is recording active; camera source capture is camera active. Resolve monitor ports and upstream graph conservatively; virtual/ambiguous routing becomes unknown, not guessed microphone.
- [x] Add tests for two concurrent streams, last-stream removal, explicit `info:null` removals, object-ID reuse, unavailable backend, malformed JSON, split arrays, multiple arrays, and strings containing brackets. Assert old inputs are unchanged. Bound decoder buffering and fail unknown on malformed/oversized input.
- [x] Run `python3 -m unittest discover -s tests -v`; confirm failures before implementing the exact interfaces.
- [x] Implement the minimal classifier and incremental state handling. Use client ownership for the installed Hyprland portal; do not rely on stream-name prefix. Metadata is not authenticated identity and must not be advertised as such.
- [x] Run the unit suite; expect all classifier tests passing.

### Task 2: Device-access observation and backend lifecycle

**Interfaces:** `camera_status(holders: frozenset[str], stable_since: float | None, now: float, available: bool) -> dict`; `run(output, stop_event, ...) -> None` with injected process/clock dependencies for tests. Exact injection signatures may be chosen by implementer and kept local to runtime tests.

- [x] Write failing tests: camera holder stable for 0.75 seconds becomes active access evidence; a shorter probe does not; last-holder disappearance clears activity; startup unavailable evidence is unknown; failed holder lookup is unknown, not empty. Test multiple devices/holders and missing permissions/tools.
- [x] Write runtime tests using fake processes and pipes for startup reconciliation, changing device set, watcher loss/overflow, PipeWire disconnect/restart, malformed child output, bounded restart backoff, and signal/unload cleanup. Assert all owned children are terminated and reaped. No real capture in tests.
- [x] Run tests and capture RED before implementation.
- [x] Implement `pw-dump -N -m` and a narrowly scoped camera watch. Use startup and event-triggered `fuser` reconciliation, not open-minus-close counts. Debounce noisy device events to at most one reconciliation per second, with a maximum one-second wait during continuous event storms; do not starve updates with trailing-only debounce. Use a slow device-discovery fallback (five seconds) for hotplug and loss recovery, not tight polling. Missing startup/watch evidence stays unknown until reconciled. Bound subprocess timeouts and stderr buffering.
- [x] Ensure Python termination, stdin closure if used, and QML process teardown also clean up grandchildren. Use explicit subprocess argument lists, not shell commands. Reconnect starts with fresh graph state; no sensitive stderr forwarding.
- [x] Run tests; expect GREEN. Run backend briefly with installed read-only interfaces, terminate it, and verify its own child PIDs exited. Do not start capture or alter desktop state.

### Task 3: Theme-native widget and delivery checks

**Interfaces:** Backend emits complete version-1 status JSON per line. QML validates that shape before replacing its snapshot, and resets to unknown on process exit or malformed data.

- [x] Add behavioral tests for output schema and combined camera/PipeWire state: positive evidence survives another unavailable detector, with limitations retained. Test startup unknown, backend failure, and direct-access wording. Run RED before backend changes. Do not write source-text assertion tests for QML.
- [x] Add the manifest and QML. Resolve backend path relative to the widget; launch through an owned Quickshell `Process`. Follow installed host property injection conventions. Use compact distinct icons for active types, plus a compact coverage/status marker when no active type is visible, so tooltip limitations remain discoverable. Unsupported paths must not force all icons permanently on. No clicking actions or popup.
- [x] Bind to live `Color.bar.text`/`Color.bar.active` roles and existing tooltip conventions; include accessible labels, horizontal/vertical geometry, and unknown status text. Watchdog or process-loss handling must not retain stale activity. Do not install to test.
- [x] Document tested paths, access-vs-streaming distinction, browser-tab blind spot, other-user/process restrictions, unsupported nonportal screen capture, and system-audio classification still needing representative live validation.
- [x] Run `python3 -m unittest discover -s tests -v`, `python3 -m compileall -q backend tests`, `python3 -m trace --count --summary --missing --coverdir /tmp/opencode/hushlight-coverage --ignore-dir /usr/lib --module unittest discover -s tests`, `omarchy plugin validate .`, and `qmlformat --normalize Widget.qml` in check/output-only mode. Run `qmllint` with installed import paths; report any host-module resolution limits honestly. Use trace results to check at least 80% backend line coverage, accounting for the runtime/entry point explicitly.
- [x] Inspect diff and document unrun checks. Update this checklist and README with actual evidence. No commit or installation. Request permission for live bar/theme testing only after local verification.

## Execution routing

Use one `general` Go writer for approved implementation and tests, per repository policy. No parallel writers or automatic Codex escalation. Usage data is unknown. If the writer cannot read external installed API references, coordinator supplies targeted excerpts; do not repeat the earlier blocked reconnaissance delegation.

## Self-review

The three tasks cover the approved indicators, conservative detection, live-theme bindings, tests, and dependency-free packaging. Installation and privileged streaming confirmation are intentionally excluded. Remaining live acceptance checks are camera probing false positives, system-audio routes, concurrency/crash behavior, theme switching, and plugin unload in the actual shell; mocks cannot establish those outcomes.
