# Event System Guide

The HoudiniMCP event system enables bidirectional communication: instead of Claude
only sending commands to Houdini, Houdini can now push events back to Claude about
scene changes, node operations, and frame changes.

## How It Works

```
Houdini Callbacks → EventCollector (buffer) → get_pending_events → MCP Bridge → Claude
```

1. **EventCollector** registers callbacks on Houdini's event system
2. Events are buffered in memory with timestamps and deduplication
3. Claude polls for events using the `get_houdini_events` tool
4. Events are returned and the buffer is cleared

## Event Types

| Event | Trigger | Details |
|-------|---------|---------|
| `scene_loaded` | .hip file opened | `{hip_file}` |
| `scene_saved` | Scene saved | `{hip_file}` |
| `scene_cleared` | File > New | `{}` |
| `node_created` | New node added under /obj | `{path, type, parent}` |
| `node_deleted` | Node removed under /obj | `{path, name}` |
| `frame_changed` | Playbar frame changes | `{frame}` |

## Using Events from Claude

### Check for Recent Changes

Ask Claude: "What's changed in Houdini since I last checked?"

Claude will call `get_houdini_events` and report any scene changes, new nodes,
deleted nodes, or frame changes.

### Subscribe to Specific Events

If you only care about certain events (e.g., just node changes), ask Claude to
subscribe:

```
Subscribe to only node_created and node_deleted events
```

Claude calls `subscribe_houdini_events` with `types: ["node_created", "node_deleted"]`.
Other events (frame changes, scene saves) will be ignored until you unsubscribe.

### Reset to All Events

Ask Claude to "subscribe to all Houdini events" to stop filtering.

## Event Deduplication

Rapid-fire events (e.g., scrubbing the playbar) are automatically deduplicated.
If the same event type + node path fires within 100ms, only the latest value is
kept. This prevents the buffer from filling with hundreds of frame_changed events
during playback.

## Buffer Size

The event buffer holds up to 1000 events. When full, the oldest events are
dropped. Under normal usage (interactive editing), this is more than enough.

## Technical Details

The EventCollector registers these Houdini callbacks:

- `hou.hipFile.addEventCallback()` — scene load, save, clear
- `hou.node("/obj").addEventCallback()` — child created/deleted
- `hou.playbar.addEventCallback()` — frame changes

Callbacks are lightweight (O(1) deque append) and add negligible overhead to
Houdini's event processing.

The collector is started and stopped with the HoudiniMCP server — no manual
setup required.
