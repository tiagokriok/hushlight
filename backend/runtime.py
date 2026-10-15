"""Backend lifecycle: it owns every child process and emits snapshots.

One `pw-dump -N -m` child streams graph updates; one `inotifywait` child only
triggers bounded `fuser` reconciliations. Camera events are debounced to at
most one reconcile per second, with a slow discovery fallback for hotplug and
lost watchers. Fixed argv lists are used throughout; no shell is involved.

All process and time dependencies are injectable so the lifecycle can be
tested with fakes and no real capture.
"""

import ctypes
import glob
import json
import os
import select
import signal
import subprocess
import sys
import time

from backend import camera as camera_module
from backend import pipewire
from backend import status as st

PW_ARGS = ("pw-dump", "-N", "-m")
CAMERA_DEVICE_PATTERNS = ("/dev/video*",)
READ_CHUNK = 65536
MAX_BACKOFF = 8.0
HOLDER_TIMEOUT = 2.0
REAP_TIMEOUT = 2.0
DEFAULT_DEBOUNCE = 0.75
DEFAULT_MIN_INTERVAL = 1.0
DEFAULT_FALLBACK_INTERVAL = 5.0
DEFAULT_MAX_WAIT = 0.5

# Linux-only: ask the kernel to SIGTERM a child when its parent dies, so a
# SIGKILL of the backend (or a QML unload) cannot orphan grandchildren.
PR_SET_PDEATHSIG = 1
_PDEATHSIG_SUPPORTED = sys.platform.startswith("linux")


def _prctl(option, arg2, arg3, arg4, arg5):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(option, arg2, arg3, arg4, arg5)


def apply_pdeathsig(parent_pid, prctl=_prctl, getppid=os.getppid, exit_fn=os._exit):
    """Set the parent-death signal and close the fork/setup race.

    prctl is best-effort: if it fails, the child keeps running rather than
    aborting. The race check exits immediately if the parent already died
    between fork and this call.
    """
    try:
        prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except Exception:
        return
    if getppid() != parent_pid:
        exit_fn(1)


def _pdeathsig_preexec():
    """Return a preexec hook for the next child, or None off Linux."""
    if not _PDEATHSIG_SUPPORTED:
        return None
    parent_pid = os.getpid()
    return lambda: apply_pdeathsig(parent_pid)


class PopenChild:
    """A child process in its own session so its whole group can be reaped."""

    def __init__(self, args, popen=subprocess.Popen):
        self.args = tuple(args)
        kwargs = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        preexec = _pdeathsig_preexec()
        if preexec is not None:
            kwargs["preexec_fn"] = preexec
        self._proc = popen(list(args), **kwargs)

    @property
    def pid(self):
        return self._proc.pid

    def fileno(self):
        return self._proc.stdout.fileno()

    def read(self):
        try:
            return os.read(self.fileno(), READ_CHUNK)
        except OSError:
            return b""

    def alive(self):
        return self._proc.poll() is None

    def close(self):
        proc = self._proc
        if proc.poll() is None:
            _signal_group(proc, signal.SIGTERM)
        try:
            proc.stdout.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=REAP_TIMEOUT)
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=REAP_TIMEOUT)
            except subprocess.TimeoutExpired:
                pass


def _signal_group(proc, sig):
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            if sig == signal.SIGKILL:
                proc.kill()
            else:
                proc.terminate()
        except OSError:
            pass


def popen_child(args):
    return PopenChild(args)


def discover_camera_devices(patterns=CAMERA_DEVICE_PATTERNS):
    """Return sorted /dev/video* paths, deduplicated across patterns."""
    found = set()
    for pattern in patterns:
        found.update(glob.glob(pattern))
    return sorted(found)


def camera_event_args(devices):
    return ["inotifywait", "-m", "-q", "-e", "open", "-e", "close", *devices]


def lookup_camera_holders(devices, runner=subprocess.run, timeout=HOLDER_TIMEOUT):
    """Return holder ids for `devices`, or None when the lookup is unavailable.

    fuser only needs read access to the device nodes. Its PIDs are opaque
    identities; they are never written to the output snapshot.
    """
    if not devices:
        return frozenset()
    kwargs = dict(capture_output=True, text=True, timeout=timeout)
    preexec = _pdeathsig_preexec()
    if preexec is not None:
        kwargs["preexec_fn"] = preexec
    try:
        result = runner(["fuser", *devices], **kwargs)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return frozenset(token for token in str(result.stdout).split() if token)


class Backend:
    """Detection state: folds graph bytes and holder snapshots into statuses."""

    def __init__(self, debounce=DEFAULT_DEBOUNCE):
        self.debounce = debounce
        self._objects = {}
        self._pipewire_available = False
        self._decode_buffer = ""
        self._camera_available = False
        self._holders = frozenset()
        self._stable_since = None

    def graph_bytes(self, data):
        """Feed raw child output. Raises DecodeError on malformed input."""
        text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
        updates, remainder = pipewire.decode_updates(self._decode_buffer + text)
        self._decode_buffer = remainder
        for batch in updates:
            self._objects = pipewire.apply_updates(self._objects, batch)
        # Only a complete array proves the graph is reachable; partial bytes
        # must not flip an unknown status into unobserved.
        if updates:
            self._pipewire_available = True

    def graph_lost(self):
        """Drop all graph state; the next snapshot reports unknown."""
        self._objects = {}
        self._decode_buffer = ""
        self._pipewire_available = False

    def reconcile_camera(self, now, available, holders):
        """Record a holder snapshot, resetting stability when it changes."""
        if holders != self._holders or available != self._camera_available:
            self._holders = holders
            self._camera_available = available
            self._stable_since = now if (available and holders) else None

    def stability_deadline(self):
        """When the current holders would cross into active, or None."""
        if self._camera_available and self._holders and self._stable_since is not None:
            return self._stable_since + self.debounce
        return None

    def snapshot(self, now):
        graph = pipewire.classify(self._objects, self._pipewire_available)
        device = camera_module.camera_status(
            self._holders, self._stable_since, now, self._camera_available,
            debounce=self.debounce)
        return {
            "version": 1,
            "microphone": graph["microphone"],
            "camera": st.merge(graph["camera"], device),
            "recording": graph["recording"],
        }


def run(output, stop_event, spawn=popen_child, select_fn=select.select,
        clock=time.monotonic, discover_devices=discover_camera_devices,
        holder_lookup=lookup_camera_holders, pw_args=PW_ARGS,
        camera_event_args=camera_event_args, debounce=DEFAULT_DEBOUNCE,
        min_interval=DEFAULT_MIN_INTERVAL,
        fallback_interval=DEFAULT_FALLBACK_INTERVAL, max_wait=DEFAULT_MAX_WAIT):
    """Run the backend until `stop_event` is set, writing JSON lines to `output`."""
    backend = Backend(debounce=debounce)

    pipewire_child = None
    camera_child = None
    devices = []
    next_reconcile = None
    last_reconcile = None
    next_fallback = None
    pipewire_backoff = 1.0
    next_pipewire_restart = 0.0
    camera_backoff = 1.0
    next_camera_restart = 0.0
    last_emitted = None

    def write_snapshot(now):
        nonlocal last_emitted
        line = json.dumps(backend.snapshot(now), sort_keys=True)
        if line != last_emitted:
            last_emitted = line
            output.write(line + "\n")
            output.flush()

    def start_pipewire(now):
        nonlocal pipewire_child, pipewire_backoff, next_pipewire_restart
        try:
            pipewire_child = spawn(list(pw_args))
        except OSError:
            pipewire_child = None
            backend.graph_lost()
            next_pipewire_restart = now + pipewire_backoff
            pipewire_backoff = min(pipewire_backoff * 2, MAX_BACKOFF)
            return
        pipewire_backoff = 1.0
        next_pipewire_restart = 0.0

    def drop_pipewire(now):
        nonlocal pipewire_child, pipewire_backoff, next_pipewire_restart
        if pipewire_child is not None:
            pipewire_child.close()
            pipewire_child = None
        backend.graph_lost()
        next_pipewire_restart = now + pipewire_backoff
        pipewire_backoff = min(pipewire_backoff * 2, MAX_BACKOFF)

    def start_camera(now):
        nonlocal camera_child, camera_backoff, next_camera_restart
        if not devices:
            camera_child = None
            return
        try:
            camera_child = spawn(camera_event_args(list(devices)))
        except OSError:
            camera_child = None
            next_camera_restart = now + camera_backoff
            camera_backoff = min(camera_backoff * 2, MAX_BACKOFF)
            return
        camera_backoff = 1.0
        next_camera_restart = 0.0

    def drop_camera(now):
        nonlocal camera_child, camera_backoff, next_camera_restart
        if camera_child is not None:
            camera_child.close()
            camera_child = None
        next_camera_restart = now + camera_backoff
        camera_backoff = min(camera_backoff * 2, MAX_BACKOFF)

    def schedule_reconcile(now):
        nonlocal next_reconcile
        earliest = now if last_reconcile is None else max(now, last_reconcile + min_interval)
        if next_reconcile is None or earliest < next_reconcile:
            next_reconcile = earliest

    def reconcile(now):
        nonlocal devices, next_reconcile, last_reconcile, next_fallback
        nonlocal camera_child, camera_backoff
        last_reconcile = now
        next_reconcile = None
        discovered = list(discover_devices())
        if discovered != devices:
            devices = discovered
            if camera_child is not None:
                camera_child.close()
                camera_child = None
            camera_backoff = 1.0
            start_camera(now)
        holders = holder_lookup(devices) if devices else frozenset()
        backend.reconcile_camera(now, holders is not None, holders or frozenset())
        if next_fallback is None or next_fallback <= now:
            next_fallback = now + fallback_interval

    try:
        start_pipewire(clock())
        reconcile(clock())
        write_snapshot(clock())

        while not stop_event.is_set():
            now = clock()
            if pipewire_child is None and now >= next_pipewire_restart:
                start_pipewire(now)
            if camera_child is None and devices and now >= next_camera_restart:
                start_camera(now)
            if next_reconcile is not None and now >= next_reconcile:
                reconcile(now)
            if next_fallback is not None and now >= next_fallback:
                reconcile(now)

            deadlines = [now + max_wait]
            if next_reconcile is not None:
                deadlines.append(next_reconcile)
            if next_fallback is not None:
                deadlines.append(next_fallback)
            if pipewire_child is None:
                deadlines.append(next_pipewire_restart)
            if camera_child is None and devices:
                deadlines.append(next_camera_restart)
            stable = backend.stability_deadline()
            if stable is not None and stable > now:
                deadlines.append(stable)
            timeout = max(0.0, min(deadlines) - now)

            read_fds = []
            if pipewire_child is not None:
                read_fds.append(pipewire_child.fileno())
            if camera_child is not None:
                read_fds.append(camera_child.fileno())
            try:
                ready, _, _ = select_fn(read_fds, [], [], timeout)
            except OSError:
                ready = []

            now = clock()
            if pipewire_child is not None and pipewire_child.fileno() in ready:
                data = pipewire_child.read()
                if not data:
                    drop_pipewire(now)
                else:
                    try:
                        backend.graph_bytes(data)
                    except pipewire.DecodeError:
                        drop_pipewire(now)
            if pipewire_child is not None and not pipewire_child.alive():
                drop_pipewire(now)

            if camera_child is not None and camera_child.fileno() in ready:
                data = camera_child.read()
                if not data:
                    drop_camera(now)
                else:
                    schedule_reconcile(now)
            if camera_child is not None and not camera_child.alive():
                drop_camera(now)

            if next_fallback is not None and now >= next_fallback:
                reconcile(now)
            write_snapshot(now)
    finally:
        if pipewire_child is not None:
            pipewire_child.close()
        if camera_child is not None:
            camera_child.close()
