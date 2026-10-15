"""Behavioral tests for camera reconciliation and backend lifecycle (Task 2).

Uses fake subprocesses and a discrete-event clock. No real capture, devices,
or child processes are touched.
"""

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from backend import pipewire as pw
from backend import status as st
from backend import runtime
from backend.runtime import Backend, run


def graph(*objects):
    return {o["id"]: o for o in objects}


_PROP_ALIASES = {
    "device_api": "device.api",
    "node_virtual": "node.virtual",
    "client_id": "client.id",
    "node_name": "node.name",
}


def node(oid, media_class, state="running", **props):
    props = dict(props)
    for key in list(props):
        if key in _PROP_ALIASES:
            props[_PROP_ALIASES[key]] = props.pop(key)
    props.setdefault("node.name", "node/%d" % oid)
    props["media.class"] = media_class
    return {"id": oid, "type": "PipeWire:Interface:Node",
            "info": {"state": state, "props": props}}


def link(oid, out_node, in_node):
    return {"id": oid, "type": "PipeWire:Interface:Link",
            "info": {"props": {"link.output.node": out_node,
                               "link.input.node": in_node}}}


def active_microphone_bytes():
    objects = graph(
        node(20, "Audio/Source", device_api="alsa", node_name="alsa_input"),
        node(30, "Stream/Input/Audio"),
        link(40, 20, 30),
    )
    return json.dumps(list(objects.values())).encode("utf-8")


def parse_lines(output):
    return [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


class BackendTests(unittest.TestCase):
    def test_snapshot_schema(self):
        backend = Backend()
        snap = backend.snapshot(0.0)
        self.assertEqual(set(snap), {"version", "microphone", "camera", "recording"})
        self.assertEqual(snap["version"], 1)
        for key in ("microphone", "camera", "recording"):
            self.assertEqual(set(snap[key]), {"state", "evidence", "limitations"})

    def test_graph_lost_resets_to_unknown(self):
        backend = Backend()
        backend.graph_bytes(active_microphone_bytes())
        self.assertEqual(backend.snapshot(0.0)["microphone"]["state"], st.STATE_ACTIVE)
        backend.graph_lost()
        self.assertEqual(backend.snapshot(0.0)["microphone"]["state"], st.STATE_UNKNOWN)

    def test_malformed_graph_raises_decode_error(self):
        backend = Backend()
        with self.assertRaises(pw.DecodeError):
            backend.graph_bytes(b'[{"id":1},]')

    def test_partial_graph_bytes_stay_unknown(self):
        backend = Backend()
        backend.graph_bytes(b'[{"id":1,')
        self.assertEqual(backend.snapshot(0.0)["microphone"]["state"], st.STATE_UNKNOWN)
        backend.graph_bytes(b'"type":"PipeWire:Interface:Node"}]')
        self.assertEqual(backend.snapshot(0.0)["microphone"]["state"], st.STATE_UNOBSERVED)

    def test_backend_debounce_is_passed_to_camera_status(self):
        backend = Backend(debounce=2.0)
        backend.graph_bytes(b"[]")
        backend.reconcile_camera(0.0, True, frozenset({"brave"}))
        self.assertEqual(backend.snapshot(1.0)["camera"]["state"], st.STATE_UNOBSERVED)
        self.assertEqual(backend.snapshot(2.0)["camera"]["state"], st.STATE_ACTIVE)

    def test_camera_probe_shorter_than_debounce_is_suppressed(self):
        backend = Backend(debounce=0.75)
        backend.graph_bytes(b"[]")
        backend.reconcile_camera(0.0, True, frozenset({"brave"}))
        self.assertEqual(backend.snapshot(0.30)["camera"]["state"], st.STATE_UNOBSERVED)
        self.assertEqual(backend.snapshot(0.75)["camera"]["state"], st.STATE_ACTIVE)

    def test_camera_last_holder_disappearance_clears(self):
        backend = Backend(debounce=0.75)
        backend.graph_bytes(b"[]")
        backend.reconcile_camera(0.0, True, frozenset({"brave"}))
        self.assertEqual(backend.snapshot(1.0)["camera"]["state"], st.STATE_ACTIVE)
        backend.reconcile_camera(1.0, True, frozenset())
        self.assertEqual(backend.snapshot(1.0)["camera"]["state"], st.STATE_UNOBSERVED)

    def test_camera_one_of_two_holders_removed_resets_stability(self):
        backend = Backend(debounce=0.75)
        backend.graph_bytes(b"[]")
        backend.reconcile_camera(0.0, True, frozenset({"brave", "obs"}))
        self.assertEqual(backend.snapshot(1.0)["camera"]["state"], st.STATE_ACTIVE)
        backend.reconcile_camera(1.0, True, frozenset({"brave"}))
        self.assertEqual(backend.snapshot(1.0)["camera"]["state"], st.STATE_UNOBSERVED)
        self.assertEqual(backend.snapshot(1.75)["camera"]["state"], st.STATE_ACTIVE)

    def test_unavailable_holder_lookup_is_unknown(self):
        backend = Backend()
        backend.reconcile_camera(0.0, False, frozenset())
        self.assertEqual(backend.snapshot(0.0)["camera"]["state"], st.STATE_UNKNOWN)

    def test_positive_activity_survives_unavailable_detector(self):
        backend = Backend()
        backend.graph_bytes(active_microphone_bytes())
        backend.reconcile_camera(0.0, False, frozenset())
        snap = backend.snapshot(1.0)
        self.assertEqual(snap["microphone"]["state"], st.STATE_ACTIVE)
        self.assertEqual(snap["camera"]["state"], st.STATE_UNKNOWN)
        self.assertEqual(snap["recording"]["state"], st.STATE_UNOBSERVED)
        self.assertTrue(snap["microphone"]["limitations"])
        self.assertTrue(snap["camera"]["limitations"])

    def test_stability_deadline_none_without_holders(self):
        backend = Backend(debounce=0.75)
        backend.reconcile_camera(0.0, True, frozenset())
        self.assertIsNone(backend.stability_deadline())


# --- deterministic subprocess harness -------------------------------------


class FakeClock:
    def __init__(self, start=0.0):
        self.t = float(start)

    def __call__(self):
        return self.t


class FakeStop:
    def __init__(self, clock, deadline):
        self.clock = clock
        self.deadline = deadline

    def is_set(self):
        return self.clock.t >= self.deadline


class FakeChild:
    def __init__(self, fd):
        self.fd = fd
        self.queue = []
        self.closed = False
        self.alive_flag = True

    def deliver(self, data):
        if data is None:
            self.alive_flag = False
            self.queue.append(b"")
        else:
            self.queue.append(data)

    def fileno(self):
        return self.fd

    def read(self):
        data = self.queue.pop(0) if self.queue else b""
        if data == b"":
            self.alive_flag = False
        return data

    def alive(self):
        return self.alive_flag

    def close(self):
        self.closed = True
        self.alive_flag = False


DEATH = object()


class Harness:
    def __init__(self, deadline):
        self.clock = FakeClock()
        self.stop = FakeStop(self.clock, deadline)
        self.children = {}
        self.spawn_log = []
        self.events = []
        self.next_fd = 10
        self.discover = []
        self.discover_calls = 0
        self.lookup = []
        self.raise_for = None
        self.select_fail_times = 0

    def spawn(self, args):
        if self.raise_for is not None and self.raise_for(args):
            raise FileNotFoundError(args[0])
        fd = self.next_fd
        self.next_fd += 1
        child = FakeChild(fd)
        self.children[fd] = child
        self.spawn_log.append((fd, list(args)))
        return child

    def discover_devices(self):
        self.discover_calls += 1
        if len(self.discover) > 1:
            return list(self.discover.pop(0))
        return list(self.discover[0]) if self.discover else []

    def holder_lookup(self, devices):
        if not devices:
            return frozenset()
        if len(self.lookup) > 1:
            return self.lookup.pop(0)
        return self.lookup[0] if self.lookup else frozenset()

    def select(self, rlist, wlist, xlist, timeout):
        if self.select_fail_times > 0:
            self.select_fail_times -= 1
            raise OSError("select interrupted")
        target = self.clock.t + max(0.0, min(timeout, 0.5))
        if self.events and self.events[0][0] <= target + 1e-9:
            t, fd, data = self.events.pop(0)
            self.clock.t = t
            if data is DEATH:
                self.children[fd].alive_flag = False
                return ([], [], [])
            self.children[fd].deliver(data)
            ready = [fd] if fd in rlist else []
            return (ready, [], [])
        self.clock.t = target
        return ([], [], [])

    def add_event(self, t, fd, data):
        self.events.append((t, fd, data))
        self.events.sort(key=lambda event: event[0])


def run_backend(harness, **overrides):
    output = io.StringIO()
    kwargs = dict(
        spawn=harness.spawn,
        select_fn=harness.select,
        clock=harness.clock,
        discover_devices=harness.discover_devices,
        holder_lookup=harness.holder_lookup,
    )
    kwargs.update(overrides)
    run(output, harness.stop, **kwargs)
    return output


class RuntimeTests(unittest.TestCase):
    def test_startup_emits_complete_schema(self):
        h = Harness(deadline=0.2)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        h.add_event(0.0, 10, b"[]\n")
        lines = parse_lines(run_backend(h))
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(line["version"], 1)

    def test_uses_fixed_argv_without_shell(self):
        h = Harness(deadline=0.2)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        run_backend(h)
        self.assertEqual(h.spawn_log[0][1], ["pw-dump", "-N", "-m"])
        cam_args = h.spawn_log[1][1]
        self.assertEqual(cam_args[0], "inotifywait")
        self.assertIn("/dev/video0", cam_args)
        self.assertNotIn("bash", cam_args)
        self.assertNotIn("sh", cam_args)
        self.assertNotIn("-c", cam_args)

    def test_cleanup_closes_all_children(self):
        h = Harness(deadline=0.3)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        run_backend(h)
        self.assertTrue(h.children)
        for child in h.children.values():
            self.assertTrue(child.closed)

    def test_camera_stable_becomes_active_in_output(self):
        h = Harness(deadline=2.0)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset({"brave"})]
        h.add_event(0.0, 10, b"[]\n")
        lines = parse_lines(run_backend(h, debounce=0.75, min_interval=0.5,
                                        fallback_interval=5.0))
        active = [l for l in lines if l["camera"]["state"] == st.STATE_ACTIVE]
        self.assertTrue(active)
        self.assertEqual(active[-1]["camera"]["evidence"], "Camera device accessed")

    def test_failed_holder_lookup_reports_unknown(self):
        h = Harness(deadline=0.6)
        h.discover = [["/dev/video0"]]
        h.lookup = [None]
        lines = parse_lines(run_backend(h))
        self.assertTrue(any(l["camera"]["state"] == st.STATE_UNKNOWN for l in lines))

    def test_missing_pipewire_tool_does_not_crash(self):
        h = Harness(deadline=0.6)
        h.discover = []
        h.lookup = [frozenset()]
        h.raise_for = lambda args: args and args[0] == "pw-dump"
        lines = parse_lines(run_backend(h))
        self.assertTrue(lines)
        self.assertTrue(any(l["microphone"]["state"] == st.STATE_UNKNOWN for l in lines))

    def test_pipewire_disconnect_resets_and_restarts(self):
        h = Harness(deadline=3.0)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        h.add_event(0.0, 10, b"[]\n")
        h.add_event(1.0, 10, None)
        lines = parse_lines(run_backend(h, fallback_interval=10.0))
        pw_spawns = [a for _, a in h.spawn_log if a[0] == "pw-dump"]
        self.assertGreaterEqual(len(pw_spawns), 2)
        self.assertTrue(any(l["microphone"]["state"] == st.STATE_UNKNOWN
                            and l["recording"]["state"] == st.STATE_UNKNOWN
                            for l in lines))

    def test_malformed_pipewire_output_resets_and_restarts(self):
        h = Harness(deadline=2.0)
        h.discover = []
        h.lookup = [frozenset()]
        h.add_event(0.0, 10, b'[{"id":1},]\n')
        lines = parse_lines(run_backend(h, fallback_interval=10.0))
        self.assertTrue(any(l["microphone"]["state"] == st.STATE_UNKNOWN for l in lines))
        pw_spawns = [a for _, a in h.spawn_log if a[0] == "pw-dump"]
        self.assertGreaterEqual(len(pw_spawns), 2)

    def test_watcher_loss_recovers(self):
        h = Harness(deadline=2.5)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        h.add_event(0.5, 11, None)
        run_backend(h, fallback_interval=5.0)
        cam_spawns = [a for _, a in h.spawn_log if a[0] == "inotifywait"]
        self.assertGreaterEqual(len(cam_spawns), 2)

    def test_device_hotplug_starts_watcher(self):
        h = Harness(deadline=2.0)
        h.discover = [[], ["/dev/video0"]]
        h.lookup = [frozenset()]
        run_backend(h, fallback_interval=0.5)
        cam_spawns = [a for _, a in h.spawn_log if a[0] == "inotifywait"]
        self.assertEqual(len(cam_spawns), 1)
        self.assertIn("/dev/video0", cam_spawns[0])

    def test_no_device_events_means_no_watcher(self):
        h = Harness(deadline=0.5)
        h.discover = [[]]
        run_backend(h)
        cam_spawns = [a for _, a in h.spawn_log if a[0] == "inotifywait"]
        self.assertEqual(cam_spawns, [])

    def test_event_storm_is_rate_limited(self):
        h = Harness(deadline=2.0)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        for i in range(18):
            h.add_event(0.01 * (i + 1), 11, b"ev\n")
        run_backend(h, min_interval=1.0, fallback_interval=100.0)
        # startup + at most one debounced reconcile inside the storm window
        self.assertLessEqual(h.discover_calls, 3)

    def test_startup_exception_still_closes_children(self):
        h = Harness(deadline=1.0)

        def boom():
            raise RuntimeError("discovery failed")

        with self.assertRaises(RuntimeError):
            run(io.StringIO(), h.stop, spawn=h.spawn, select_fn=h.select,
                clock=h.clock, discover_devices=boom, holder_lookup=h.holder_lookup)
        self.assertTrue(h.children)
        self.assertTrue(all(child.closed for child in h.children.values()))

    def test_survives_select_error(self):
        h = Harness(deadline=0.6)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        h.select_fail_times = 1
        self.assertTrue(parse_lines(run_backend(h)))

    def test_camera_spawn_failure_does_not_crash(self):
        h = Harness(deadline=0.6)
        h.discover = [["/dev/video0"]]
        h.lookup = [frozenset()]
        h.raise_for = lambda args: bool(args) and args[0] == "inotifywait"
        self.assertTrue(parse_lines(run_backend(h)))

    def test_device_change_closes_old_watcher(self):
        h = Harness(deadline=2.0)
        h.discover = [["/dev/video0"], ["/dev/video1"]]
        h.lookup = [frozenset()]
        run_backend(h, fallback_interval=0.5)
        self.assertTrue(h.children[11].closed)
        self.assertTrue(any(args[0] == "inotifywait" and "/dev/video1" in args
                            for _, args in h.spawn_log))

    def test_pipewire_death_without_read_resets(self):
        h = Harness(deadline=2.0)
        h.discover = []
        h.lookup = [frozenset()]
        h.add_event(0.0, 10, b"[]\n")
        h.add_event(0.9, 10, DEATH)
        lines = parse_lines(run_backend(h, fallback_interval=10.0))
        self.assertTrue(any(l["microphone"]["state"] == st.STATE_UNKNOWN for l in lines))
        pw_spawns = [a for _, a in h.spawn_log if a[0] == "pw-dump"]
        self.assertGreaterEqual(len(pw_spawns), 2)


class FakeStdout:
    def __init__(self, fd):
        self.fd = fd
        self.closed = False

    def fileno(self):
        return self.fd

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self):
        self.pid = 4242
        self.alive = True
        self.stdout = FakeStdout(987654)
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout=None):
        self.alive = False
        return 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1


class AdapterTests(unittest.TestCase):
    def test_popen_child_uses_session_and_handles_bad_fd(self):
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return FakeProc()

        child = runtime.PopenChild(["/bin/true"], popen=fake_popen)
        self.assertEqual(captured["args"], ["/bin/true"])
        self.assertTrue(captured["kwargs"]["start_new_session"])
        self.assertEqual(child.fileno(), 987654)
        self.assertEqual(child.read(), b"")
        self.assertTrue(child.alive())
        with mock.patch("backend.runtime.os.killpg") as killpg:
            child.close()
            killpg.assert_called_once_with(4242, runtime.signal.SIGTERM)
        self.assertTrue(child._proc.stdout.closed)

    def test_popen_child_escalates_to_kill_on_stuck_wait(self):
        class StuckProc(FakeProc):
            def wait(self, timeout=None):
                self.waits = getattr(self, "waits", 0) + 1
                if self.waits == 1:
                    raise runtime.subprocess.TimeoutExpired("x", timeout)
                self.alive = False
                return 0

        proc = StuckProc()
        child = runtime.PopenChild(["/bin/true"], popen=lambda args, **kwargs: proc)
        with mock.patch("backend.runtime.os.killpg") as killpg:
            child.close()
        signals = [call.args[1] for call in killpg.call_args_list]
        self.assertIn(runtime.signal.SIGKILL, signals)

    def test_signal_group_prefers_process_group(self):
        proc = FakeProc()
        with mock.patch("backend.runtime.os.killpg") as killpg:
            runtime._signal_group(proc, runtime.signal.SIGTERM)
        killpg.assert_called_once_with(proc.pid, runtime.signal.SIGTERM)
        self.assertEqual(proc.terminated, 0)

    def test_signal_group_falls_back_to_terminate(self):
        proc = FakeProc()
        with mock.patch("backend.runtime.os.killpg", side_effect=ProcessLookupError):
            runtime._signal_group(proc, runtime.signal.SIGTERM)
        self.assertEqual(proc.terminated, 1)

    def test_signal_group_kill_uses_kill(self):
        proc = FakeProc()
        with mock.patch("backend.runtime.os.killpg", side_effect=ProcessLookupError):
            runtime._signal_group(proc, runtime.signal.SIGKILL)
        self.assertEqual(proc.killed, 1)

    def test_default_discovery_globs_devices(self):
        with mock.patch("backend.runtime.glob.glob",
                        return_value=["/dev/video1", "/dev/video0"]):
            self.assertEqual(runtime.discover_camera_devices(),
                             ["/dev/video0", "/dev/video1"])

    def test_lookup_camera_holders(self):
        self.assertEqual(runtime.lookup_camera_holders([]), frozenset())
        ok = lambda *a, **k: SimpleNamespace(returncode=0, stdout=" 11 22 \n")
        self.assertEqual(runtime.lookup_camera_holders(["/dev/video0"], runner=ok),
                         frozenset({"11", "22"}))
        none = lambda *a, **k: SimpleNamespace(returncode=1, stdout="")
        self.assertEqual(runtime.lookup_camera_holders(["/dev/video0"], runner=none),
                         frozenset())

        def broken(*a, **k):
            raise OSError("fuser missing")

        self.assertIsNone(runtime.lookup_camera_holders(["/dev/video0"], runner=broken))
        bad = lambda *a, **k: SimpleNamespace(returncode=2, stdout="x")
        self.assertIsNone(runtime.lookup_camera_holders(["/dev/video0"], runner=bad))

    def test_apply_pdeathsig_detects_parent_race(self):
        calls = []
        exits = []
        runtime.apply_pdeathsig(1234, prctl=lambda *a: calls.append(a),
                                getppid=lambda: 1, exit_fn=exits.append)
        self.assertEqual(calls[0][0], runtime.PR_SET_PDEATHSIG)
        self.assertEqual(calls[0][1], signal.SIGTERM)
        self.assertEqual(exits, [1])

    def test_apply_pdeathsig_no_exit_when_parent_alive(self):
        exits = []
        runtime.apply_pdeathsig(1234, prctl=lambda *a: None,
                                getppid=lambda: 1234, exit_fn=exits.append)
        self.assertEqual(exits, [])

    def test_apply_pdeathsig_swallows_prctl_errors(self):
        exits = []

        def bad(*a):
            raise OSError("no prctl")

        runtime.apply_pdeathsig(1, prctl=bad, getppid=lambda: 1, exit_fn=exits.append)
        self.assertEqual(exits, [])

    def test_popen_child_sets_parent_death_signal(self):
        captured = {}

        def fake_popen(args, **kwargs):
            captured["kwargs"] = kwargs
            return FakeProc()

        runtime.PopenChild(["/bin/true"], popen=fake_popen)
        if sys.platform.startswith("linux"):
            self.assertIsNotNone(captured["kwargs"].get("preexec_fn"))
        else:
            self.assertIsNone(captured["kwargs"].get("preexec_fn"))

    def test_holder_lookup_passes_pdeathsig_setup(self):
        captured = {}

        def runner(args, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(returncode=1, stdout="")

        runtime.lookup_camera_holders(["/dev/video0"], runner=runner)
        if sys.platform.startswith("linux"):
            self.assertIn("preexec_fn", captured)

    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_PDEATHSIG is Linux-only")
    def test_owned_children_die_when_parent_is_sigkilled(self):
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "pdeathsig_parent_helper.py")
        interpreter = shutil.which("python3") or sys.executable
        parent = subprocess.Popen([interpreter, helper],
                                  stdout=subprocess.PIPE, text=True)
        grandchild = None
        try:
            line = parent.stdout.readline().strip()
            self.assertTrue(line, "helper did not report a child pid")
            grandchild = int(line)
            self.assertTrue(_process_alive(grandchild))
            parent.kill()
            parent.wait(timeout=5)
            self.assertTrue(_wait_until_dead(grandchild, timeout=5),
                            "grandchild survived its parent's SIGKILL")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
            if parent.stdout is not None:
                parent.stdout.close()
            if grandchild is not None and _process_alive(grandchild):
                try:
                    os.kill(grandchild, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _process_alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as handle:
            data = handle.read()
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return False
    state = data.rsplit(")", 1)[1].split()[0]
    return state != "Z"


def _wait_until_dead(pid, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.05)
    return not _process_alive(pid)


if __name__ == "__main__":
    unittest.main()
