# Roadmap: Houdini → Claude Event Callback System

## Goal
Enable Houdini to push events (scene changes, render completion, user actions) to Claude, making the interaction bidirectional instead of today's one-way command model where only Claude initiates actions.

## Current Limitation
Communication is strictly request-response: Claude sends a command via MCP → bridge → TCP → Houdini, and gets a response. There's no mechanism for Houdini to notify Claude when something happens (user modifies a node, scene loads, render finishes, etc.).

## Architecture

```
┌──────────────────────────────────────────────┐
│ Houdini                                      │
│                                              │
│  hou.hipFile.addEventCallback()              │
│  hou.node("/obj").addEventCallback()         │
│  hou.playbar.addEventCallback()              │
│         │                                    │
│         ▼                                    │
│  EventCollector (new module)                 │
│    - Buffers events                          │
│    - Deduplicates rapid-fire changes         │
│    - Exposes via new "get_events" command    │
│                                              │
│  HoudiniMCPServer (existing)                 │
│    - New handler: "get_pending_events"       │
│    - New handler: "subscribe_events"         │
└──────────────┬───────────────────────────────┘
               │ TCP :9876
┌──────────────▼───────────────────────────────┐
│ houdini_mcp_server.py                        │
│  - Polls for events periodically             │
│  - Or: SSE/notification MCP resource         │
│  - Exposes events to Claude as tool results  │
└──────────────────────────────────────────────┘
```

## Phases

### Phase 1: Event Collection Inside Houdini
**Effort: ~2-3 days**

- [ ] Create `event_collector.py` module
- [ ] Register Houdini callbacks:
  - `hou.hipFile.addEventCallback()` — scene load, save, new scene
  - Node event callbacks on `/obj` — child added, deleted, renamed
  - `hou.playbar.addEventCallback()` — frame change, playback start/stop
- [ ] Event buffer (deque with max size) to store recent events
- [ ] Deduplication: collapse rapid successive changes to same node into one event
- [ ] Timestamp each event
- [ ] Event schema:
  ```python
  {
      "type": "node_created" | "node_deleted" | "node_modified" | "scene_loaded" | "scene_saved" | "frame_changed" | "render_complete",
      "timestamp": float,
      "details": { ... }  # type-specific payload
  }
  ```

### Phase 2: Server Integration
**Effort: ~1-2 days**

- [ ] Add `get_pending_events` command to `server.py` dispatcher
  - Returns buffered events since last poll and clears the buffer
  - Optional `since_timestamp` parameter for selective retrieval
- [ ] Add `subscribe_events` command to configure which event types to collect
  - Default: all events
  - Allows filtering: `{"types": ["node_created", "node_deleted"]}`
- [ ] Wire `EventCollector` into `HoudiniMCPServer.__init__` — start/stop with server

### Phase 3: Bridge-Side Polling
**Effort: ~1-2 days**

- [ ] Add `get_houdini_events` MCP tool in `houdini_mcp_server.py`
  - Calls `get_pending_events` on the Houdini side
  - Returns formatted event list to Claude
- [ ] Add optional background polling (async task):
  - Periodically call `get_pending_events` (e.g. every 2 seconds)
  - Queue events for the next Claude interaction
  - Configurable: enabled/disabled, poll interval

### Phase 4: MCP Notifications (Advanced)
**Effort: ~3-4 days**

- [ ] Investigate MCP notification mechanism (server → client notifications)
- [ ] If supported, push events as MCP notifications instead of polling
- [ ] Implement as MCP resource subscription:
  - `houdini://events` resource that Claude can subscribe to
  - Events pushed as resource updates
- [ ] Fallback: keep polling for MCP clients that don't support notifications

### Phase 5: Selective Subscriptions & Filters
**Effort: ~2-3 days**

- [ ] Per-session event subscriptions (Claude can subscribe/unsubscribe)
- [ ] Event filtering by node path pattern (e.g. only `/obj/character/*`)
- [ ] Event aggregation window (batch 100ms of changes into one event)
- [ ] Priority levels: some events interrupt Claude (errors), others queue

## Event Types to Support

| Event | Source Callback | Details Payload |
|-------|----------------|-----------------|
| `scene_loaded` | `hou.hipFile.addEventCallback` | `{hip_file, node_count}` |
| `scene_saved` | `hou.hipFile.addEventCallback` | `{hip_file}` |
| `node_created` | node event callback | `{path, type, parent}` |
| `node_deleted` | node event callback | `{path, name}` |
| `node_modified` | node event callback | `{path, changed_parms}` |
| `node_renamed` | node event callback | `{path, old_name, new_name}` |
| `frame_changed` | `hou.playbar.addEventCallback` | `{frame}` |
| `selection_changed` | `hou.pypanel` or custom | `{selected_paths}` |
| `render_complete` | post-render callback | `{filepath, duration}` |

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Event storm from rapid parameter changes | Debounce/dedup in EventCollector (collapse within 100ms window) |
| Performance impact from callbacks | Callbacks only append to deque (O(1)); no heavy processing |
| Buffer overflow on long idle periods | Cap buffer at ~1000 events; oldest dropped with warning |
| Houdini callbacks not firing for all node types | Test across geo, cam, light, subnet, GLTF hierarchy; document gaps |
| MCP protocol may not support server-initiated messages | Polling fallback in Phase 3 works regardless |

## Success Criteria
- Claude can ask "what changed since I last checked?" and get accurate answers
- User modifying a node in Houdini is visible to Claude on next interaction
- Event collection adds <1ms overhead per callback
- No events are lost under normal usage (buffer sized for typical session)
