# TODO

## Plugin: silent bind-failure on port collision

**Symptom:** When a previous Houdini process is still holding port 9876 (e.g. wedged / zombie session after a restart), the new Houdini's plugin will return `"Houdini MCP Server is already running."` from `houdinimcp.start_server()`, but the new server isn't actually bound to anything reachable. The bridge keeps timing out / refusing to connect because port 9876 is owned by the dead PID.

**Diagnosis trail:**
- `ss -tlnp | grep 9876` showed `houdini-bin pid=<old PID>` still LISTENing on 9876.
- New Houdini reported the server was already running and refused to re-bind.
- User had no signal that the port-bind silently failed at some earlier point.

**Suggested fixes (any one would help):**
- Have `start_server()` verify the listener is genuinely bound — try `socket.getsockname()` on the stored socket, or attempt a quick self-connect to localhost:9876, before reporting "already running."
- On `start_server()` invocation, if a previous plugin instance is detected in this Houdini session but the socket is unhealthy, tear it down and rebind cleanly instead of returning a no-op.
- When the initial bind fails (`OSError: address already in use`), surface that as a Houdini error/warning popup rather than swallowing it — currently the user only finds out via `ss` / `netstat`.

**Why it matters:** The current behavior makes a stale port collision look like a working server, which sends users hunting for problems in the bridge or in their network setup when the actual fix is `kill <stale-pid>` followed by a clean restart.
