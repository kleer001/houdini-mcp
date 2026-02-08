"""
event_collector.py — Collects Houdini events for push to Claude via MCP.

Registers callbacks on hipFile, node tree, and playbar events.
Stores events in a bounded deque with deduplication for rapid-fire changes.
"""
import time
from collections import deque

import hou

MAX_BUFFER_SIZE = 1000
DEDUP_WINDOW = 0.1  # seconds — collapse changes to same node within this window


class EventCollector:
    """Buffers Houdini events for retrieval by the MCP bridge."""

    def __init__(self, max_size=MAX_BUFFER_SIZE):
        self._events = deque(maxlen=max_size)
        self._subscribed_types = None  # None = all types
        self._callbacks_registered = False
        self._last_event_key = None
        self._last_event_time = 0.0

    # ---- Public API ----

    def start(self):
        """Register all Houdini callbacks."""
        if self._callbacks_registered:
            return
        hou.hipFile.addEventCallback(self._on_hip_event)
        obj = hou.node("/obj")
        if obj:
            obj.addEventCallback(
                (hou.nodeEventType.ChildCreated, hou.nodeEventType.ChildDeleted),
                self._on_node_event,
            )
        hou.playbar.addEventCallback(self._on_playbar_event)
        self._callbacks_registered = True

    def stop(self):
        """Remove all registered callbacks."""
        if not self._callbacks_registered:
            return
        try:
            hou.hipFile.removeEventCallback(self._on_hip_event)
        except Exception:
            pass
        obj = hou.node("/obj")
        if obj:
            try:
                obj.removeEventCallback(
                    (hou.nodeEventType.ChildCreated, hou.nodeEventType.ChildDeleted),
                    self._on_node_event,
                )
            except Exception:
                pass
        try:
            hou.playbar.removeEventCallback(self._on_playbar_event)
        except Exception:
            pass
        self._callbacks_registered = False

    def subscribe(self, event_types=None):
        """Set which event types to collect. None = all."""
        self._subscribed_types = set(event_types) if event_types else None

    def get_pending(self, since=None):
        """Return and clear buffered events. Optionally filter by timestamp."""
        if since is not None:
            events = [e for e in self._events if e["timestamp"] > since]
        else:
            events = list(self._events)
        self._events.clear()
        return events

    @property
    def event_count(self):
        return len(self._events)

    # ---- Internal ----

    def _should_collect(self, event_type):
        if self._subscribed_types is None:
            return True
        return event_type in self._subscribed_types

    def _dedup_key(self, event_type, details):
        """Generate a key for deduplication."""
        path = details.get("path", "")
        return f"{event_type}:{path}"

    def _push(self, event_type, details):
        if not self._should_collect(event_type):
            return
        now = time.time()
        key = self._dedup_key(event_type, details)

        # Deduplicate rapid successive events with same key
        if key == self._last_event_key and (now - self._last_event_time) < DEDUP_WINDOW:
            # Update the last event in-place (overwrite details)
            if self._events:
                self._events[-1]["details"] = details
                self._events[-1]["timestamp"] = now
            self._last_event_time = now
            return

        self._events.append({
            "type": event_type,
            "timestamp": now,
            "details": details,
        })
        self._last_event_key = key
        self._last_event_time = now

    # ---- Houdini Callbacks ----

    def _on_hip_event(self, event_type):
        if event_type == hou.hipFileEventType.AfterLoad:
            self._push("scene_loaded", {
                "hip_file": hou.hipFile.path(),
            })
        elif event_type == hou.hipFileEventType.AfterSave:
            self._push("scene_saved", {
                "hip_file": hou.hipFile.path(),
            })
        elif event_type == hou.hipFileEventType.AfterClear:
            self._push("scene_cleared", {})

    def _on_node_event(self, **kwargs):
        node = kwargs.get("node")
        child_node = kwargs.get("child_node")
        event_type = kwargs.get("event_type")

        if event_type == hou.nodeEventType.ChildCreated and child_node:
            self._push("node_created", {
                "path": child_node.path(),
                "type": child_node.type().name(),
                "parent": node.path() if node else "",
            })
        elif event_type == hou.nodeEventType.ChildDeleted and child_node:
            self._push("node_deleted", {
                "path": child_node.path(),
                "name": child_node.name(),
            })

    def _on_playbar_event(self, event_type, frame):
        if event_type == hou.playbarEvent.FrameChanged:
            self._push("frame_changed", {"frame": frame})
