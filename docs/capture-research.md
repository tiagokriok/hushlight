# Capture research

## Scope

Read-only metadata checks on this machine, with capture started and stopped by
the user. No audio, video, screen contents, browser profiles, or window titles
were collected. These were manual snapshots, not automated acceptance tests.

Primary targets are Discord and browsers. Installed targets include Discord
and Brave. Broad application coverage is the goal, not a verified guarantee.

## Observations

| Scenario | Evidence | Result |
| --- | --- | --- |
| Initial playback | Running `Stream/Output/Audio` linked to `Audio/Sink` | Playback must not count as capture |
| Discord microphone test | Running `Stream/Input/Audio`, active link from ALSA `Audio/Source`; PulseAudio source output uncorked | Microphone capture observable |
| Discord microphone test stopped | Recording stream, capture link, and PulseAudio source output disappeared | Stop observable |
| Brave live camera preview | User confirmed live image; PipeWire camera sources remained suspended and no video capture stream appeared | PipeWire-only camera detection misses this path; underlying mechanism not established |
| Brave camera test page | Two running Brave audio input streams linked to an ALSA audio source | Page also captured microphone despite requested camera-only scenario |
| Brave test page closed | Audio capture streams disappeared | Audio stop observable |
| Brave browser-tab sharing | User confirmed active tab sharing; no video capture stream visible in PipeWire | Tested tab-sharing path not observable through PipeWire |
| Brave window or entire-screen sharing | Running portal-owned `Video/Source` actively linked to Brave `Stream/Input/Video` | Portal screen capture observable; exact selected surface not recorded |
| Sharing stopped and page closed | Portal source, video input, and microphone streams disappeared; camera sources suspended | Cleanup observable at final snapshot |

Discord camera and screen sharing were not tested: the user reported these
features unavailable to them. System-audio capture, concurrent independent
sessions, application crashes, plugin lifecycle, and theme switching remain
unverified.

## Classification implications

- Use active capture links and stream state, not hardware presence or playback.
- Resolve source ownership and metadata: both cameras and portal screen capture
  can expose `Video/Source`.
- Discord's microphone stream advertised `WEBRTC VoiceEngine`, not Discord.
  Friendly application labels alone cannot establish identity.
- The observed portal screen source was owned by
  `xdg-desktop-portal-hyprland`. Its `node.name` did not match the
  `xdph-streaming-` prefix found in upstream source; do not depend on that prefix.
- No visible PipeWire capture means only no capture observed through that
  interface. It does not establish global inactivity.
- Missing camera and internal tab-sharing coverage must be explicit. Do not
  infer active camera streaming from a device being open or available.

## Available integration

Installed: PipeWire 1.6.8, WirePlumber 0.5.17, Quickshell 0.3.1,
xdg-desktop-portal 1.22.1, portal-hyprland 1.4.1, Python 3,
`pw-dump`, `pw-mon`, `pactl`, `qmltestrunner`, and `qmllint`.

`pw-dump --monitor` documents JSON arrays describing changes. A watcher must
process successive arrays and removals, clear stale state on disconnect, and
stop its subprocess on unload. Actual monitoring lifecycle remains untested.

Installed Omarchy references:

- `/usr/share/omarchy/shell/README.md`: manifest, user plugins, lifecycle.
- `/usr/share/omarchy/shell/plugins/bar/README.md`: live bar colors and tooltips.
- `/usr/share/omarchy/shell/Commons/Color.qml`: reactive theme surface roles.
- `/usr/share/omarchy/shell/Ui/BarWidget.qml`: widget host properties.

Portal ScreenCast introspection exposes session creation and start methods,
not a public global active-session listing. No D-Bus traffic monitoring was
performed. No privileged or process-file-descriptor inspection was performed.

## Next design constraints

### Follow-up: direct camera signals

With separate user permission, a subsequent device-holder test using `fuser`
found a `brave` process holding `/dev/video2` during a user-confirmed live
camera preview. After the user stopped the preview and closed the page,
`fuser` reported no holders for any of `/dev/video0` through `/dev/video3`.
Only process IDs and process names were resolved; no frames, command lines,
or browser data were read. This establishes observable device access for the
tested Brave path, not an independent proof of streaming. Other-user holders
and restricted process metadata may be invisible to an unprivileged observer.

`inotifywait`, `fuser`, and `lsof` are installed. A temporary unprivileged
`inotifywait` watcher successfully observed device open/close events during a
second Brave preview test. At the active snapshot, `/dev/video2` had one more
open than close and `fuser` identified Brave. After stop, a
`CLOSE_WRITE,CLOSE` event balanced it; all four watched devices had zero net
opens and no visible holders. The temporary watcher was explicitly stopped
and its exit was confirmed.

Hundreds of brief read-only open/close pairs also occurred across the devices.
Their origin was not established. An open event alone would produce false
alerts; sustained-access filtering and bounded reconciliation require tests.
Inotify counts are not authoritative reference counts: event coalescing,
overflow, existing opens at startup, descriptor duplication, and watch loss
must be handled without declaring global inactivity.

`bpftrace` and `bpftool` were not found on PATH;
LensGuard was not found among queried installed packages. The kernel exposes
BTF, but unprivileged BPF is disabled (`unprivileged_bpf_disabled=2`). No
eBPF observer was installed or run. A privileged streaming observer therefore
remains a separate option requiring explicit setup approval and validation.

Read-only sysfs inspection found both USB camera devices runtime-suspended
after the tests. Their video-class directories expose identity, power, and
debug attributes, but no explicit active-streaming attribute was found.
USB runtime power is not an adequate capture signal: it describes power,
not whether frames are being captured, and control operations can wake a
device. Upstream UVC driver source also uses power-management references for
control ioctls, not exclusively streaming:
`https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/usb/uvc/uvc_v4l2.c`.
This is upstream reference evidence, not an audit of the installed kernel.

Device-open notifications likewise do not establish streaming and cannot
reconstruct existing opens on watcher startup. No reliable non-invasive
direct-camera signal has been established. Do not use power, file opens, or
busy-device probing as confirmed camera capture. No camera devices were
opened or probed during this follow-up.

Prefer a small QML widget and an event-driven backend using installed tools.
Do not claim all-app coverage. Investigate direct-camera observability before
choosing whether additional narrowly scoped signals are justified. Internal
browser capture may require browser integration, which is not approved scope.

No plugin, dependencies, installation, desktop configuration changes, commits,
or publication were made during these checks.
