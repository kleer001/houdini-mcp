# Best Practices — MCP & environment

Operational findings for running the bridge and the Houdini environment (licensing, logs, port handoff, autostart, HDA code sync, run-script). General rules live in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md).

### File > Run Script Only Accepts .cmd, Not .py

> Houdini 21.0.631

**The File > Run Script... menu maps to HScript's `source` command, which parses HScript only.** Picking a `.py` file fails with `Application doesn't support input redirection` (HScript tries to interpret the Python content). Renaming a Python file to `.cmd` doesn't help — same parser, same failure.

**Anti-pattern:** Shipped a plugin's setup as `<plugin>_setup.py` and told users to File > Run Script it. Users hit cryptic HScript parse errors on the first non-comment line.

**Fix — dispatcher pattern:** Ship a tiny `.cmd` that resolves its own path via `$arg0` and exec's a sibling `.py`:

```
python -c "import os; p=os.path.join(os.path.dirname(os.path.abspath(r'$arg0')),'setup.py'); exec(compile(open(p).read(),p,'exec'),{'__name__':'__main__','__file__':p})"
```

Two extra notes:
- HScript's `python -c "..."` argument **must be a single line** — embedded newlines break because HScript reparses subsequent lines as commands. Backslash continuation joins lines but strips the newline.
- `$arg0` inside a sourced `.cmd` evaluates to the `.cmd`'s own absolute path, which is the cleanest way to find sibling files (HDAs, .py modules) the user dropped next to it.

---

### HDA Script Sync

> Houdini 21.0.631

**Editing HDA script files on disk does NOT update the embedded code inside the `.hdalc`.** The HDA definition carries its own copy of `PythonModule.py`, `OnCreated.py`, etc. If you only change the on-disk files, the live HDA keeps running the old code.

**Anti-pattern:** Changed `PythonModule.py` in the repo, committed, but didn't update the HDA definition. The node in Houdini still ran the old logic.

**Fix:** After modifying any HDA script file, push the updated code into the HDA definition — via Type Properties → Scripts in the Houdini UI, or via MCP (`set_hda_section_content` / `update_hda`). Treat HDA sync as part of the commit.

---

### GUI/Headless Port Handoff

**Problem:** Only one process can listen on the MCP port (9876). A headless session the bridge auto-launched squats the port, so a GUI opened later cannot take over — and only the GUI has a GPU.

**Fix (built in):** A GUI (interactive) session always wins the port. On `start()`, a GUI that finds the port busy writes a short-lived claim file and retries binding; a headless server sees the claim in its poll loop, stops, and frees the port (its `hython` process then exits). The bridge reconnects to the GUI on its next call. When the GUI closes, the bridge re-spawns headless.

**Notes:** `hou.isUIAvailable()` decides who yields. The installer adds `import houdinimcp` to the GUI startup hooks (see [Autostart Survives a Broken Co-Plugin](#autostart-survives-a-broken-co-plugin)) so a GUI auto-starts the server on launch. The bridge honours `HOUDINIMCP_NO_HEADLESS=1` to forbid the headless fallback entirely (GUI-only mode) — leave it unset for automatic juggling. Validated: Houdini 21.0.631.

---

### Autostart Survives a Broken Co-Plugin

**Problem:** The GUI plugin does not start and nothing listens on port 9876, even though Houdini opens normally.

**Symptom:** No `HoudiniMCP server started …` line in Houdini's console, and no Python traceback either — the autostart simply never ran. Often paired with an unrelated plugin failing loudly at launch (e.g. `Traceback from Unhandled Exception Loading … redshift4houdini.so`, a version-mismatched render engine).

**Cause:** `pythonrc.py` runs *early*, during `initApplication` (operator-table build). An unhandled exception from another DSO loaded in that phase aborts the whole startup-script step, so `pythonrc.py` never executes. The main window still comes up because per-DSO load errors are caught individually.

**Fix (built in):** Attach the autostart from hooks that run *after* init and survive the abort. The installer adds `import houdinimcp` to `123.py` (empty launch) and `456.py` (scene load) as well as `pythonrc.py` (fast path). `start_server()` is idempotent — it guards on `hou.session.houdinimcp_server` — so importing from several hooks starts the server at most once. Proven with a trace: with a broken Redshift plugin, `pythonrc.py` did not run but `456.py` did, and the server bound from `456.py`. Validated: Houdini 21.0.631.

---

### License Server Repointed by Installer Upgrade

**Problem:** Bridge-launched Houdini reports `No licenses could be found to run this application` after a SideFX installer upgrade — even though a valid license exists on the machine.

**Symptom:** `hython`/GUI cannot acquire a license; `hserver -l` shows `Connected To: https://www.sidefx.com/license/sesinetd`; `sesictrl print-license` is empty or lists only expired keys.

**Cause:** The installer rewrites `~/.sesi_licenses.pref` to the SideFX **login server**, which serves no active license for accounts that use a local license server. The valid key stays on the local `sesinetd` at `localhost:1715`.

**Anti-pattern:** Ran `sesictrl sync-licenses` to "restore" the license. It returns `HTTP 422: Associated server is not found` — sync is for account-based login licensing, not a local server, so it is the wrong path.

**Fix:** Repoint hserver to the local server and verify the key is there:

```bash
sesictrl print-license -h localhost --show-all   # confirm the valid key (e.g. "Houdini Indie 21.0")
hserver -S http://localhost:1715                 # set the running service
hserver -l                                       # expect: Connected To: http://localhost:1715
hython -c "import hou; print(hou.licenseCategory())"   # expect: Indie
```

**Note:** hserver is a **system** service (`/etc/systemd/system/hserver.service`). `-S` sets the already-running service; editing `~/.sesi_licenses.pref` alone does not take effect until hserver restarts. Validated: Houdini 21.0.631.

---

### Unlicensed Houdini Error-Loop Fills the tmpfs Log

**Problem:** `/tmp` fills to 100%, after which every MCP call, shell command, and license checkout fails with `ENOSPC` or a misleading `No licenses could be found`.

**Symptom:** A single multi-GB file such as `<scratchpad>/houdini_gui3.log`; `df -h /tmp` shows the tmpfs at 100%; `rm` of the file does **not** free the space.

**Cause:** An **unlicensed** Houdini launched ad-hoc — stdout/stderr redirected into a scratchpad file on `/tmp` (tmpfs, sized to RAM) — error-loops (license nag, or a broken co-plugin traceback) and writes GB per minute. `rm` unlinks the name, but the running process still holds the file descriptor, so tmpfs space is not reclaimed until the process closes it.

**Fix:** Reclaim the space without killing an unsaved scene — truncate the held-open fd, then stop the writer:

```bash
ls -l /proc/<pid>/fd | grep houdini_gui   # find fds pointing at the (deleted) log
truncate -s 0 /proc/<pid>/fd/1            # frees tmpfs immediately; Houdini stays up
# then close the Houdini session, or: kill <pid>
```

**Prevent:** Never redirect a long-running Houdini process's stdout/stderr into the tmpfs scratchpad. Send it to `/dev/null` or a real disk. The bridge's own auto-launch logs to a bounded path (`/tmp/houdini_temp/hserver.log`); this failure comes only from ad-hoc launches that tee into the scratchpad. Validated: Houdini 21.0.631.
