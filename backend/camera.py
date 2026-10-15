"""Camera device-access status from bounded holder reconciliation.

Direct device access (`fuser` holders) is weaker evidence than a confirmed
PipeWire capture stream. A holder is only reported active after it has stayed
present for a debounce window, so the brief read-only probe pairs seen on this
machine cannot raise an alert. The evidence text says "accessed", never
"recording" or "streaming".
"""

from backend import status as st

# A holder must persist this long before it counts as active access.
DEBOUNCE_SECONDS = 0.75

_LIMITATIONS = (
    "Direct device access is not confirmed streaming",
    "Holders invisible to this user are not observed",
    "Internal browser-tab capture is not supported",
)


def camera_status(holders, stable_since, now, available, debounce=DEBOUNCE_SECONDS):
    """Return the camera status for a holder snapshot.

    holders      current holder identities (opaque; never emitted)
    stable_since when the current non-empty holder set began, or None
    now          monotonic time
    available    whether holder lookup succeeded
    debounce     seconds a holder must persist before counting as active
    """
    if not available:
        return st.make(st.STATE_UNKNOWN, "Camera device holder lookup unavailable",
                       _LIMITATIONS)
    if not holders:
        return st.make(st.STATE_UNOBSERVED, "No camera device holders observed",
                       _LIMITATIONS)
    if stable_since is not None and now - stable_since >= debounce:
        return st.make(st.STATE_ACTIVE, "Camera device accessed", _LIMITATIONS)
    return st.make(st.STATE_UNOBSERVED, "Camera device access not sustained",
                   _LIMITATIONS)
