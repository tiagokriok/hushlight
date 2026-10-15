# Hushlight

Theme-native privacy indicators for the Omarchy top bar.

## Handoff status

Documentation only. No implementation, dependencies, Git repository, or installed plugin has been created. The next agent should inspect the current Omarchy installation before choosing implementation details. Do not treat earlier feasibility statements as verified detection capabilities.

## User request and agreed requirements

Create an Omarchy top-bar plugin inspired by macOS privacy indicators:

- Indicate active microphone use.
- Indicate active camera use.
- Indicate screen or system-audio recording.
- Use the user's currently selected Omarchy theme, not hardcoded macOS orange, green, and purple.
- Follow theme changes while running, without requiring manual plugin edits.

The reference was a screenshot describing macOS orange microphone, green camera, and purple recording indicators. Those colors explain the inspiration only; they are not requirements.

The user has requested this project directory and handoff. Implementation has not yet been requested in this session.

## UX direction, subject to implementation validation

Keep the bar presence small, using privacy dots or similarly compact marks. Distinguish microphone, camera, and recording with icons or labels/tooltips, rather than color alone. Theme palettes can contain visually similar colors.

A click-to-open detail popup showing the responsible applications was suggested, but is not a confirmed requirement. Ask before expanding scope. Do not build a settings system or replace the whole bar.

Do not confuse idle hardware availability with active capture. Do not imply that an absent indicator proves that no application is recording. Establish and document how unknown status differs from confirmed inactivity.

## Omarchy integration already inspected

On this machine, Omarchy uses a single Quickshell-based `omarchy-shell`. Plugins use QML plus a `manifest.json`.

Read these installed references before implementation:

- `/usr/share/omarchy/shell/README.md`: plugin manifest, lifecycle, IPC, installation, and security model.
- `/usr/share/omarchy/shell/plugins/README.md`: built-in plugin catalogue.
- `/usr/share/omarchy/shell/plugins/bar/README.md`: bar conventions and configuration.
- Relevant existing widget implementations and theme services. Inspect these to discover the actual theme API; do not invent property names or hardcode a palette.
- `/home/tiagokriok/.pi/agent/skills/omarchy/SKILL.md` and its `plugins.md` guide, if available.

User-owned installation location:

```text
~/.config/omarchy/plugins/<plugin-id>/
  manifest.json
  Widget.qml
```

Plugin ID is not finalized. Choose a valid namespaced ID after checking the installed manifest schema. A bar widget declares the `bar-widget` kind and a `barWidget` entry point. Additional files or kinds should exist only when needed.

Useful commands, verified as documented on this installation:

```bash
omarchy plugin --help
omarchy bar --help
omarchy plugin validate <plugin-folder>
omarchy-shell shell rescanPlugins
omarchy plugin enable <plugin-id>
omarchy bar move <plugin-id> --section right
```

User plugin files hot-reload. Persistent bar layout lives in `~/.config/omarchy/shell.json`.

Never edit `/usr/share/omarchy/`. Keep source in this project and obtain permission before installing/enabling it or modifying desktop configuration. Do not clone a built-in plugin merely for reference: cloning automatically switches the user's active plugin.

## Detection research required

Determine available, trustworthy capture signals before promising full coverage:

- Microphone: investigate active PipeWire recording streams, including applications using PulseAudio compatibility. Exclude playback and unrelated monitor streams.
- Camera: investigate PipeWire cameras and direct V4L2 access. A PipeWire-only approach may miss applications accessing devices directly.
- Screen capture: investigate the installed Wayland desktop portal and PipeWire capture lifecycle. Do not assume every PipeWire video stream is screen capture.
- System audio capture: distinguish loopback/monitor recording from ordinary microphone capture and playback.
- Application attribution: investigate available metadata. Do not assume an app name or process identity is always available or trustworthy.

These are investigation targets, not a prescribed backend. Prefer existing platform interfaces and installed dependencies. Avoid elevated privileges, invasive process inspection, and tight polling loops. Report limitations instead of claiming macOS-equivalent security guarantees.

Plugins execute unsandboxed within the user's shell process. Keep command execution narrowly scoped and avoid logging sensitive window titles or capture metadata unnecessarily.

## Suggested next steps

1. Inspect local project/global instructions, runtime/tooling, installed Omarchy APIs, and available capture interfaces.
2. Propose the smallest design with explicit supported/unsupported capture paths. Resolve any product decisions with the user before implementation.
3. Establish the project tooling only as needed; prefer QML and existing system facilities over a new framework or service.
4. Write failing tests for nontrivial detection/state logic before implementation. Use controlled fixtures or mocks rather than tests that merely assert source-file contents.
5. Implement theme-native indicators and appropriate accessible labels using existing shell conventions.
6. Validate the manifest and run relevant tests/lint. With permission, test in the live shell.

## Acceptance evidence to collect

- Microphone capture starts/stops and updates the indicator.
- Camera capture starts/stops and updates the indicator on each supported access path.
- Screen and system-audio recording are classified correctly for supported applications.
- Playback alone does not trigger a capture indicator.
- Concurrent capture sessions remain indicated until the last relevant session ends.
- Crashed capture applications do not leave stale active indicators.
- Switching Omarchy themes updates styling without hardcoded macOS colors.
- Capture types remain distinguishable when theme colors are similar.
- Missing backends or unsupported paths are documented and never presented as proof of privacy.
- Plugin reload and disable do not leave background processes or subscriptions behind.

Use representative applications actually available on the user's machine. Record which scenarios were tested and which remain unverified. Do not commit, publish, install dependencies, or modify the user's live desktop without the appropriate authorization.
