"""PipeWire graph framing and capture classification.

`pw-dump -N -m` streams a JSON array per change batch. This module frames
those arrays incrementally, folds them into an object table, and classifies
the running capture streams into microphone / camera / recording statuses.

The classifier is deliberately conservative: it uses active links plus source
ownership, never hardware presence, playback, or stream names. Routing it
cannot decide is reported as `unknown`, not guessed.
"""

import json

from backend import status as st

# Refuse to buffer an unbounded amount of partial JSON from a wedged child.
MAX_BUFFER = 4 * 1024 * 1024

# Running input streams are the only capture candidates. Output streams are
# playback and must never raise an indicator.
CAPTURE_STREAMS = {
    "Stream/Input/Audio": "audio",
    "Stream/Input/Video": "video",
}


class DecodeError(ValueError):
    """Raised when the child stream is malformed or too large to frame."""


def decode_updates(buffer):
    """Split complete top-level JSON arrays off `buffer`.

    Returns (updates, remainder) where `updates` is a list of parsed arrays.
    Bracket characters inside JSON strings are ignored. A partial trailing
    array is returned as the remainder; malformed or oversized input raises
    DecodeError so the caller can drop to `unknown`.
    """
    if len(buffer) > MAX_BUFFER:
        raise DecodeError("input buffer exceeded %d bytes" % MAX_BUFFER)

    updates = []
    index = 0
    length = len(buffer)
    while True:
        while index < length and buffer[index] in " \t\r\n":
            index += 1
        if index >= length:
            return updates, ""
        if buffer[index] != "[":
            raise DecodeError("expected a JSON array")

        start = index
        depth = 0
        in_string = False
        escaped = False
        complete = False
        scan = index
        while scan < length:
            char = buffer[scan]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    complete = True
                    scan += 1
                    break
            scan += 1

        if not complete:
            remainder = buffer[start:]
            if len(remainder) > MAX_BUFFER:
                raise DecodeError("partial array exceeded %d bytes" % MAX_BUFFER)
            return updates, remainder

        chunk = buffer[start:scan]
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError as exc:
            raise DecodeError(str(exc)) from exc
        if not isinstance(parsed, list) or not all(isinstance(el, dict) for el in parsed):
            raise DecodeError("expected an array of objects")
        updates.append(parsed)
        index = scan


def apply_updates(objects, updates):
    """Fold one update batch into a fresh object table.

    `info: null` means removal. Reused ids replace the stale entry. The input
    table is never mutated.
    """
    result = dict(objects)
    for entry in updates:
        object_id = entry.get("id")
        if object_id is None:
            continue
        if entry.get("info") is None:
            result.pop(object_id, None)
        else:
            result[object_id] = entry
    return result


def classify(objects, available):
    """Classify the current graph into microphone / camera / recording."""
    limitations = {
        "microphone": st.microphone_limitations(),
        "camera": st.camera_limitations(),
        "recording": st.recording_limitations(),
    }
    if not available:
        return {
            "microphone": st.make(st.STATE_UNKNOWN, st.EV_PIPEWIRE_DOWN,
                                  limitations["microphone"]),
            "camera": st.make(st.STATE_UNKNOWN, st.EV_PIPEWIRE_DOWN,
                              limitations["camera"]),
            "recording": st.make(st.STATE_UNKNOWN, st.EV_PIPEWIRE_DOWN,
                                 limitations["recording"]),
        }

    nodes = {}
    clients = {}
    for object_id, entry in objects.items():
        kind = entry.get("type")
        if kind == "PipeWire:Interface:Node":
            nodes[object_id] = entry
        elif kind == "PipeWire:Interface:Client":
            clients[object_id] = entry

    upstream = _upstream_map(objects)

    has_mic = has_system_audio = has_screen = False
    has_camera = False
    ambiguous_audio = ambiguous_video = False

    for stream_id, entry in nodes.items():
        props = _props(entry)
        stream_kind = CAPTURE_STREAMS.get(props.get("media.class"))
        if stream_kind is None or _state(entry) != "running":
            continue

        producers = upstream.get(stream_id, [])
        if not producers:
            if stream_kind == "audio":
                ambiguous_audio = True
            else:
                ambiguous_video = True
            continue

        for producer_id in producers:
            producer = nodes.get(producer_id)
            if producer is None:
                if stream_kind == "audio":
                    ambiguous_audio = True
                else:
                    ambiguous_video = True
                continue
            producer_props = _props(producer)
            if stream_kind == "audio":
                verdict = _classify_audio(producer_props)
                if verdict == "microphone":
                    has_mic = True
                elif verdict == "system-audio":
                    has_system_audio = True
                else:
                    ambiguous_audio = True
            else:
                verdict = _classify_video(producer_props, _owner_props(producer, clients))
                if verdict == "camera":
                    has_camera = True
                elif verdict == "screen":
                    has_screen = True
                else:
                    ambiguous_video = True

    return {
        "microphone": _indicator(has_mic, ambiguous_audio, st.EV_MIC_ACTIVE, limitations["microphone"]),
        "camera": _indicator(has_camera, ambiguous_video, st.EV_CAM_CAPTURE, limitations["camera"]),
        "recording": _recording(has_system_audio, has_screen,
                                ambiguous_audio or ambiguous_video, limitations["recording"]),
    }


def _indicator(active, ambiguous, active_evidence, limitations):
    if active:
        return st.make(st.STATE_ACTIVE, active_evidence, limitations)
    if ambiguous:
        return st.make(st.STATE_UNKNOWN, st.EV_UNCLASSIFIED, limitations)
    return st.make(st.STATE_UNOBSERVED, st.EV_UNOBSERVED, limitations)


def _recording(system_audio, screen, ambiguous, limitations):
    if system_audio and screen:
        return st.make(st.STATE_ACTIVE, st.EV_REC_MIXED, limitations)
    if screen:
        return st.make(st.STATE_ACTIVE, st.EV_REC_SCREEN, limitations)
    if system_audio:
        return st.make(st.STATE_ACTIVE, st.EV_REC_SYSTEM_AUDIO, limitations)
    if ambiguous:
        return st.make(st.STATE_UNKNOWN, st.EV_UNCLASSIFIED, limitations)
    return st.make(st.STATE_UNOBSERVED, st.EV_UNOBSERVED, limitations)


def _classify_audio(props):
    """Return 'microphone', 'system-audio', or 'ambiguous' for a producer."""
    media_class = props.get("media.class")
    name = str(props.get("node.name", ""))
    if media_class == "Audio/Sink":
        return "system-audio"
    if name.endswith(".monitor") or props.get("monitor") == "true":
        return "system-audio"
    if props.get("device.api") == "alsa":
        return "microphone"
    return "ambiguous"


def _classify_video(props, owner):
    """Return 'camera', 'screen', or 'ambiguous' for a video producer."""
    if props.get("device.api") == "v4l2":
        return "camera"
    binary = str(owner.get("application.process.binary", "")).lower()
    name = str(owner.get("application.name", "")).lower()
    if binary.startswith("xdg-desktop-portal") or name.startswith("xdg-desktop-portal"):
        return "screen"
    return "ambiguous"


def _owner_props(node, clients):
    """Client properties that own `node`, falling back to the node's own props."""
    props = _props(node)
    client = clients.get(_as_int(props.get("client.id")))
    if client is not None:
        return _props(client)
    return props


def _upstream_map(objects):
    """Map each node id to the node ids that feed it."""
    upstream = {}
    for entry in objects.values():
        if entry.get("type") != "PipeWire:Interface:Link":
            continue
        props = _props(entry)
        info = entry.get("info") if isinstance(entry.get("info"), dict) else {}
        output_node = _as_int(info.get("output-node-id"))
        input_node = _as_int(info.get("input-node-id"))
        if output_node is None:
            output_node = _as_int(props.get("link.output.node"))
        if input_node is None:
            input_node = _as_int(props.get("link.input.node"))
        if output_node is None or input_node is None:
            continue
        upstream.setdefault(input_node, []).append(output_node)
    return upstream


def _props(entry):
    info = entry.get("info")
    if not isinstance(info, dict):
        return {}
    props = info.get("props")
    return props if isinstance(props, dict) else {}


def _state(entry):
    info = entry.get("info")
    if isinstance(info, dict):
        return info.get("state")
    return None


def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
