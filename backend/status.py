"""Status values shared by the classifiers and the runtime merge.

A status is an immutable-shaped dict:

    {"state": "active" | "unobserved" | "unknown",
     "evidence": "plain text",
     "limitations": ["plain text", ...]}

`unobserved` means no activity was observed on a supported path. It is never
proof of global inactivity. `unknown` means the evidence was unavailable,
incomplete, or unclassifiable. Layering two statuses keeps a positive
observation from being hidden by a simultaneous coverage gap.
"""

STATE_ACTIVE = "active"
STATE_UNOBSERVED = "unobserved"
STATE_UNKNOWN = "unknown"

# Evidence wording. Kept central so the widget and tests share one vocabulary.
EV_MIC_ACTIVE = "Microphone capture observed"
EV_REC_SYSTEM_AUDIO = "System audio capture observed"
EV_REC_SCREEN = "Screen capture observed"
EV_REC_MIXED = "System audio and screen capture observed"
EV_CAM_CAPTURE = "Camera capture observed"
EV_UNOBSERVED = "No capture observed on supported paths"
EV_UNCLASSIFIED = "Capture state could not be classified"
EV_PIPEWIRE_DOWN = "PipeWire graph unavailable"

# Limitations. Conservative coverage notes, not guarantees of safety.
LIM_PIPEWIRE = "Only PipeWire-visible streams are observed"
LIM_BROWSER = "Internal browser-tab capture is not supported"
LIM_OTHER_USERS = "Other-user and restricted processes are not observed"
LIM_NONPORTAL = "Non-portal screen capture may be invisible"
LIM_SYSTEM_AUDIO = "System-audio loopback classification is not live-validated"

_MIC_LIMITATIONS = (LIM_PIPEWIRE, LIM_BROWSER, LIM_OTHER_USERS)
_REC_LIMITATIONS = (LIM_PIPEWIRE, LIM_NONPORTAL, LIM_OTHER_USERS, LIM_SYSTEM_AUDIO)
_CAM_LIMITATIONS = (LIM_PIPEWIRE, LIM_BROWSER, LIM_OTHER_USERS)

_RANK = {STATE_UNOBSERVED: 0, STATE_UNKNOWN: 1, STATE_ACTIVE: 2}


def make(state, evidence, limitations=()):
    """Build a status dict. Copies the limitations so callers can't alias it."""
    return {"state": state, "evidence": evidence, "limitations": list(limitations)}


def microphone_limitations():
    return list(_MIC_LIMITATIONS)


def recording_limitations():
    return list(_REC_LIMITATIONS)


def camera_limitations():
    return list(_CAM_LIMITATIONS)


def merge(first, second):
    """Combine two statuses for the same indicator.

    Positive evidence wins over a gap; an explicit unknown is stronger than a
    bare unobserved. Limitations from both sides are retained.
    """
    if first["state"] == STATE_ACTIVE:
        base, extra = first, second
    elif second["state"] == STATE_ACTIVE:
        base, extra = second, first
    elif first["state"] == STATE_UNKNOWN:
        base, extra = first, second
    elif second["state"] == STATE_UNKNOWN:
        base, extra = second, first
    else:
        base, extra = first, second

    limitations = list(base["limitations"])
    for item in extra["limitations"]:
        if item not in limitations:
            limitations.append(item)
    return {"state": base["state"], "evidence": base["evidence"],
            "limitations": limitations}
