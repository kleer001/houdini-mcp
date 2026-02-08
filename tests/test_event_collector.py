"""Tests for event_collector.py — EventCollector with mocked hou."""
import sys
import time
import types

import pytest


# Mock hou module before importing event_collector
@pytest.fixture(autouse=True)
def mock_hou(monkeypatch):
    """Set up a mock hou module with event types and callbacks."""
    hou = types.ModuleType("hou")

    # hipFile
    hip_file = types.SimpleNamespace()
    hip_file._callbacks = []
    hip_file.addEventCallback = lambda cb: hip_file._callbacks.append(cb)
    hip_file.removeEventCallback = lambda cb: hip_file._callbacks.remove(cb) if cb in hip_file._callbacks else None
    hip_file.path = lambda: "/tmp/test.hip"
    hou.hipFile = hip_file

    # hipFileEventType
    hou.hipFileEventType = types.SimpleNamespace(
        AfterLoad="AfterLoad",
        AfterSave="AfterSave",
        AfterClear="AfterClear",
    )

    # node event types
    hou.nodeEventType = types.SimpleNamespace(
        ChildCreated="ChildCreated",
        ChildDeleted="ChildDeleted",
    )

    # playbar
    playbar = types.SimpleNamespace()
    playbar._callbacks = []
    playbar.addEventCallback = lambda cb: playbar._callbacks.append(cb)
    playbar.removeEventCallback = lambda cb: playbar._callbacks.remove(cb) if cb in playbar._callbacks else None
    hou.playbar = playbar

    hou.playbarEvent = types.SimpleNamespace(
        FrameChanged="FrameChanged",
    )

    # /obj node
    obj_node = types.SimpleNamespace()
    obj_node._callbacks = []
    obj_node.path = lambda: "/obj"

    def add_event_callback(event_types, cb):
        obj_node._callbacks.append(cb)

    def remove_event_callback(event_types, cb):
        if cb in obj_node._callbacks:
            obj_node._callbacks.remove(cb)

    obj_node.addEventCallback = add_event_callback
    obj_node.removeEventCallback = remove_event_callback

    def mock_node(path):
        if path == "/obj":
            return obj_node
        return None

    hou.node = mock_node

    # Clear any cached event_collector before setting up fresh hou
    for mod_name in list(sys.modules):
        if "event_collector" in mod_name:
            del sys.modules[mod_name]

    monkeypatch.setitem(sys.modules, "hou", hou)
    yield hou

    # Cleanup
    if "hou" in sys.modules:
        del sys.modules["hou"]
    # Remove cached event_collector module so next test gets fresh import
    for mod_name in list(sys.modules):
        if "event_collector" in mod_name:
            del sys.modules[mod_name]


def _import_collector():
    """Import EventCollector fresh (after mock is set up)."""
    from houdinimcp.event_collector import EventCollector
    return EventCollector


class TestEventCollector:
    def test_start_registers_callbacks(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        assert len(mock_hou.hipFile._callbacks) == 1
        assert len(mock_hou.playbar._callbacks) == 1
        ec.stop()

    def test_stop_removes_callbacks(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        ec.stop()
        assert len(mock_hou.hipFile._callbacks) == 0
        assert len(mock_hou.playbar._callbacks) == 0

    def test_double_start_no_duplicate(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        ec.start()  # should not register again
        assert len(mock_hou.hipFile._callbacks) == 1
        ec.stop()

    def test_hip_event_scene_loaded(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        # Simulate AfterLoad event
        for cb in mock_hou.hipFile._callbacks:
            cb(mock_hou.hipFileEventType.AfterLoad)
        events = ec.get_pending()
        assert len(events) == 1
        assert events[0]["type"] == "scene_loaded"
        assert events[0]["details"]["hip_file"] == "/tmp/test.hip"
        ec.stop()

    def test_hip_event_scene_saved(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        for cb in mock_hou.hipFile._callbacks:
            cb(mock_hou.hipFileEventType.AfterSave)
        events = ec.get_pending()
        assert len(events) == 1
        assert events[0]["type"] == "scene_saved"
        ec.stop()

    def test_playbar_frame_changed(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        for cb in mock_hou.playbar._callbacks:
            cb(mock_hou.playbarEvent.FrameChanged, 42)
        events = ec.get_pending()
        assert len(events) == 1
        assert events[0]["type"] == "frame_changed"
        assert events[0]["details"]["frame"] == 42
        ec.stop()

    def test_get_pending_clears_buffer(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        for cb in mock_hou.hipFile._callbacks:
            cb(mock_hou.hipFileEventType.AfterSave)
        assert len(ec.get_pending()) == 1
        assert len(ec.get_pending()) == 0  # cleared
        ec.stop()

    def test_subscribe_filters_events(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.subscribe(["scene_saved"])
        ec.start()
        for cb in mock_hou.hipFile._callbacks:
            cb(mock_hou.hipFileEventType.AfterLoad)  # should be filtered
            cb(mock_hou.hipFileEventType.AfterSave)  # should pass
        events = ec.get_pending()
        assert len(events) == 1
        assert events[0]["type"] == "scene_saved"
        ec.stop()

    def test_dedup_rapid_events(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        # Fire frame_changed rapidly — should deduplicate
        for cb in mock_hou.playbar._callbacks:
            cb(mock_hou.playbarEvent.FrameChanged, 1)
            cb(mock_hou.playbarEvent.FrameChanged, 2)
            cb(mock_hou.playbarEvent.FrameChanged, 3)
        events = ec.get_pending()
        # Rapid fire within dedup window → collapsed to 1 event
        assert len(events) == 1
        assert events[0]["details"]["frame"] == 3  # last value wins
        ec.stop()

    def test_buffer_max_size(self, mock_hou):
        EC = _import_collector()
        ec = EC(max_size=5)
        ec.start()
        # Need to space out events to avoid dedup
        for i in range(10):
            ec._push("test_event", {"index": i})
            ec._last_event_key = None  # reset dedup
        events = ec.get_pending()
        assert len(events) == 5  # capped at max_size
        ec.stop()

    def test_get_pending_since_filter(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()

        # Push event with known time
        before = time.time()
        for cb in mock_hou.hipFile._callbacks:
            cb(mock_hou.hipFileEventType.AfterSave)
        after = time.time()

        # Events before 'before' should be empty
        events = ec.get_pending(since=after + 1)
        assert len(events) == 0
        ec.stop()

    def test_event_has_timestamp(self, mock_hou):
        EC = _import_collector()
        ec = EC()
        ec.start()
        for cb in mock_hou.hipFile._callbacks:
            cb(mock_hou.hipFileEventType.AfterSave)
        events = ec.get_pending()
        assert "timestamp" in events[0]
        assert isinstance(events[0]["timestamp"], float)
        ec.stop()
