"""Behavioral tests for the PipeWire graph classifier (Task 1)."""

import json
import unittest

from backend import pipewire as pw
from backend import status as st


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


def client(oid, **props):
    return {"id": oid, "type": "PipeWire:Interface:Client",
            "info": {"props": props}}


def port(oid, node_id, direction):
    return {"id": oid, "type": "PipeWire:Interface:Port",
            "info": {"props": {"node.id": node_id, "port.direction": direction}}}


def link(oid, out_node, in_node):
    return {"id": oid, "type": "PipeWire:Interface:Link",
            "info": {"props": {"link.output.node": out_node,
                               "link.input.node": in_node}}}


def link_info(oid, out_node, in_node):
    """A link that exposes only info-level endpoint fields, as real pw-dump can."""
    return {"id": oid, "type": "PipeWire:Interface:Link",
            "info": {"output-node-id": out_node, "input-node-id": in_node}}


def graph(*objects):
    return {o["id"]: o for o in objects}


class ClassifyTests(unittest.TestCase):
    def test_available_empty_graph_is_unobserved(self):
        result = pw.classify({}, True)
        for key in ("microphone", "camera", "recording"):
            self.assertEqual(result[key]["state"], st.STATE_UNOBSERVED)
            self.assertIsInstance(result[key]["limitations"], list)
            self.assertTrue(result[key]["limitations"])

    def test_unavailable_backend_is_unknown(self):
        result = pw.classify({}, False)
        for key in ("microphone", "camera", "recording"):
            self.assertEqual(result[key]["state"], st.STATE_UNKNOWN)

    def test_playback_only_is_unobserved(self):
        objects = graph(
            node(20, "Audio/Sink", node_name="alsa_output"),
            node(30, "Stream/Output/Audio", client_id=5),
            client(5, **{"application.name": "Player"}),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_UNOBSERVED)
        self.assertEqual(result["recording"]["state"], st.STATE_UNOBSERVED)
        self.assertEqual(result["camera"]["state"], st.STATE_UNOBSERVED)

    def test_suspended_hardware_is_unobserved(self):
        objects = graph(
            node(20, "Audio/Source", state="suspended", device_api="alsa"),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_UNOBSERVED)

    def test_alsa_microphone_capture_is_microphone_active(self):
        objects = graph(
            node(20, "Audio/Source", mode="in", device_api="alsa",
                 node_name="alsa_input.usb"),
            node(30, "Stream/Input/Audio", client_id=7),
            client(7, **{"application.name": "Discord",
                         "application.process.binary": "Discord"}),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_ACTIVE)
        self.assertIn("Microphone", result["microphone"]["evidence"])
        self.assertEqual(result["recording"]["state"], st.STATE_UNOBSERVED)
        self.assertEqual(result["camera"]["state"], st.STATE_UNOBSERVED)

    def test_sink_monitor_capture_is_recording_not_microphone(self):
        objects = graph(
            node(20, "Audio/Source", device_api="alsa",
                 node_name="alsa_output.pci.monitor"),
            node(30, "Stream/Input/Audio", client_id=7),
            client(7, **{"application.name": "Recorder"}),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["recording"]["state"], st.STATE_ACTIVE)
        self.assertEqual(result["microphone"]["state"], st.STATE_UNOBSERVED)

    def test_virtual_ambiguous_audio_source_is_unknown(self):
        objects = graph(
            node(20, "Audio/Source", node_virtual="true",
                 node_name="virtual_source"),
            node(30, "Stream/Input/Audio", client_id=7),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_UNKNOWN)
        self.assertEqual(result["recording"]["state"], st.STATE_UNKNOWN)

    def test_portal_screen_capture_is_recording(self):
        objects = graph(
            client(5, **{"application.process.binary": "xdg-desktop-portal-hyprland",
                         "application.name": "xdg-desktop-portal-hyprland"}),
            node(20, "Video/Source", client_id=5, node_name="xdph-stream",
                 device_api="pipewire"),
            node(30, "Stream/Input/Video", client_id=9),
            client(9, **{"application.process.binary": "brave"}),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["recording"]["state"], st.STATE_ACTIVE)
        self.assertIn("Screen", result["recording"]["evidence"])
        self.assertEqual(result["camera"]["state"], st.STATE_UNOBSERVED)

    def test_v4l2_camera_source_capture_is_camera_active(self):
        objects = graph(
            node(20, "Video/Source", device_api="v4l2", node_name="v4l2_input"),
            node(30, "Stream/Input/Video", client_id=9),
            client(9, **{"application.process.binary": "brave"}),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["camera"]["state"], st.STATE_ACTIVE)
        self.assertIn("Camera", result["camera"]["evidence"])
        self.assertEqual(result["recording"]["state"], st.STATE_UNOBSERVED)

    def test_unclassifiable_video_source_is_unknown(self):
        objects = graph(
            node(20, "Video/Source", node_name="mystery"),
            node(30, "Stream/Input/Video", client_id=9),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["camera"]["state"], st.STATE_UNKNOWN)
        self.assertEqual(result["recording"]["state"], st.STATE_UNKNOWN)

    def test_two_concurrent_streams_both_active(self):
        objects = graph(
            node(20, "Audio/Source", device_api="alsa", node_name="alsa_input"),
            node(22, "Video/Source", device_api="v4l2", node_name="v4l2_input"),
            node(30, "Stream/Input/Audio", client_id=7),
            node(32, "Stream/Input/Video", client_id=9),
            link(40, 20, 30),
            link(42, 22, 32),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_ACTIVE)
        self.assertEqual(result["camera"]["state"], st.STATE_ACTIVE)

    def test_positive_wins_over_simultaneous_ambiguity(self):
        objects = graph(
            node(20, "Audio/Source", device_api="alsa", node_name="alsa_input"),
            node(22, "Audio/Source", node_virtual="true", node_name="virtual"),
            node(30, "Stream/Input/Audio", client_id=7),
            node(32, "Stream/Input/Audio", client_id=8),
            link(40, 20, 30),
            link(42, 22, 32),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_ACTIVE)
        self.assertEqual(result["recording"]["state"], st.STATE_UNKNOWN)

    def test_client_id_numeric_string_resolves_owner(self):
        objects = graph(
            client(5, **{"application.process.binary": "xdg-desktop-portal-hyprland"}),
            node(20, "Video/Source", client_id="5", device_api="pipewire", node_name="xdg"),
            node(30, "Stream/Input/Video", client_id=9),
            link(40, 20, 30),
        )
        result = pw.classify(objects, True)
        self.assertEqual(result["recording"]["state"], st.STATE_ACTIVE)

    def test_info_level_link_fields_are_used(self):
        objects = {
            20: node(20, "Audio/Source", device_api="alsa", node_name="alsa_input"),
            30: node(30, "Stream/Input/Audio", client_id=7),
            40: link_info(40, 20, 30),
        }
        result = pw.classify(objects, True)
        self.assertEqual(result["microphone"]["state"], st.STATE_ACTIVE)

    def test_classify_does_not_mutate_input(self):
        objects = graph(
            node(20, "Audio/Source", device_api="alsa", node_name="alsa_input"),
            node(30, "Stream/Input/Audio", client_id=7),
            link(40, 20, 30),
        )
        before = json.dumps(objects, sort_keys=True)
        pw.classify(objects, True)
        self.assertEqual(json.dumps(objects, sort_keys=True), before)


class ApplyUpdatesTests(unittest.TestCase):
    def test_apply_updates_adds_and_replaces(self):
        objects = {}
        result = pw.apply_updates(objects, [node(1, "Audio/Source"), link(2, 1, 1)])
        self.assertEqual(len(result), 2)
        self.assertEqual(objects, {})
        result2 = pw.apply_updates(result, [node(1, "Audio/Sink")])
        self.assertEqual(result2[1]["info"]["props"]["media.class"], "Audio/Sink")
        self.assertEqual(result[1]["info"]["props"]["media.class"], "Audio/Source")

    def test_apply_updates_removes_on_null_info(self):
        objects = {1: node(1, "Audio/Source")}
        result = pw.apply_updates(objects, [{"id": 1, "type": "PipeWire:Interface:Node",
                                             "info": None}])
        self.assertNotIn(1, result)
        self.assertIn(1, objects)

    def test_apply_updates_id_reuse_replaces_stale(self):
        objects = {1: node(1, "Audio/Source", node_name="first")}
        result = pw.apply_updates(objects, [node(1, "Audio/Source", node_name="second")])
        self.assertEqual(result[1]["info"]["props"]["node.name"], "second")
        self.assertEqual(len(result), 1)


class DecodeTests(unittest.TestCase):
    def test_single_complete_array(self):
        updates, remainder = pw.decode_updates('[{"id":1}]')
        self.assertEqual(updates, [[{"id": 1}]])
        self.assertEqual(remainder, "")

    def test_split_array_across_chunks(self):
        updates, remainder = pw.decode_updates('[{"id":1},')
        self.assertEqual(updates, [])
        self.assertEqual(remainder, '[{"id":1},')
        updates, remainder = pw.decode_updates(remainder + '{"id":2}]')
        self.assertEqual(updates, [[{"id": 1}, {"id": 2}]])
        self.assertEqual(remainder, "")

    def test_multiple_arrays_in_one_chunk(self):
        updates, remainder = pw.decode_updates('[]\n[{"id":3}]')
        self.assertEqual(updates, [[], [{"id": 3}]])
        self.assertEqual(remainder, "")

    def test_brackets_inside_strings_do_not_confuse_framing(self):
        payload = '[{"a":"x]y[z","b":"\\"]"}]'
        updates, remainder = pw.decode_updates(payload)
        self.assertEqual(updates, [[{"a": "x]y[z", "b": '"]'}]])
        self.assertEqual(remainder, "")

    def test_malformed_json_raises(self):
        with self.assertRaises(pw.DecodeError):
            pw.decode_updates('[{"id":1},]')

    def test_non_array_payload_raises(self):
        with self.assertRaises(pw.DecodeError):
            pw.decode_updates('"nope"')

    def test_non_object_elements_raise(self):
        with self.assertRaises(pw.DecodeError):
            pw.decode_updates('[1, 2]')

    def test_oversized_buffer_raises(self):
        with self.assertRaises(pw.DecodeError):
            pw.decode_updates("[" + " " * (pw.MAX_BUFFER + 1))

    def test_leading_whitespace_is_tolerated(self):
        updates, remainder = pw.decode_updates('  \n []')
        self.assertEqual(updates, [[]])
        self.assertEqual(remainder, "")


if __name__ == "__main__":
    unittest.main()
