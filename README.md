# Hushlight

Theme-native privacy indicators for the Omarchy bar.

A small circle appears only when the microphone, camera, or recording is active. It follows your Omarchy theme and shows what is on in a tooltip. No hardcoded colors, no popup, no settings.

Hushlight is conservative: it reports only what it can observe on supported paths. An absent indicator never proves that nothing is recording.

## Indicators

| Mark | Meaning |
| --- | --- |
| Hollow circle | Microphone active |
| Filled circle | Microphone and camera active |
| Filled circle with a hole | Camera active |

Omarchy already shows recording in the bar, so Hushlight no longer adds a separate mark for it.

## Install

```bash
omarchy plugin add https://github.com/yourname/hushlight.git --enable
```

Or clone the repository into `~/.config/omarchy/plugins/hushlight.privacy/` and run:

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable hushlight.privacy
```

The widget goes in the right section by default. It starts disabled until enabled.

## Requirements

- Omarchy on Arch Linux with PipeWire
- `python3` on `PATH`

The plugin runs a small Python backend as a subprocess of the shell. It watches PipeWire and camera-device access, and emits one JSON status line per change. No network, no root, no extra packages.

## What it detects

| Scenario | Status |
| --- | --- |
| Microphone via PipeWire / PulseAudio | Supported |
| System audio (loopback) capture | Supported, classification not live-validated |
| Screen capture through the Hyprland portal | Supported |
| Camera via PipeWire | `device.api: v4l2` only |
| Direct V4L2 camera access | Access only, not confirmed streaming |
| Browser tab capture (no portal) | Not visible |
| Non-portal screen capture | Possibly invisible |
| libcamera / other video sources | Reported unknown |

## Removal

```bash
omarchy plugin disable hushlight.privacy
omarchy plugin remove hushlight.privacy
```

## License

MIT
