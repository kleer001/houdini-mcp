# Phase 0: Remove OPUS Integration

**Goal:** Strip all OPUS/RapidAPI code. ~610 lines removed, 6 tools deleted.

**Drop dependencies:** `langchain` (optional, OPUS-only), `python-dotenv` (only loads `urls.env`)

## houdini_mcp_server.py

1. Delete OPUS imports and setup block (lines 36-80): `requests`, `dotenv`, `urljoin`, `langchain`, all `RAPIDAPI_*` constants and URL construction
2. Delete all OPUS helper functions (lines 88-404): `fix_rgb`, `get_all_component_names`, `get_struct_params`, `format_params`, `get_color_params`, `get_param_json`, `get_formatted_opus_params`, `check_rgbs`, `create_opus_batch`, `create_opus_component`, `variate_opus_result`
3. Delete 6 OPUS MCP tools (lines 735-844): `opus_get_model_names`, `opus_get_model_params_schema`, `opus_create_model`, `opus_variate_model`, `opus_check_job_status`, `opus_import_model_url`
4. Delete `get_opus_job_result` helper (lines 847-884)
5. Remove `"with OPUS API integration"` from FastMCP description string (line 536)
6. Remove RapidAPI validation check in `main()` (lines 892-896)

## server.py

1. Delete OPUS imports (lines 17-20): `zipfile`, `urlparse`, `uuid`
2. Delete `import_opus_url` entry from command dispatch dict (line 167)
3. Delete `_download_file` helper (lines 480-520)
4. Delete `_unzip_file` helper (lines 522-541)
5. Delete `handle_import_opus_url` handler (lines 543-657)

## Other files

1. Delete `urls.env` entirely
2. `README.md`: Remove Section 5 "OPUS integration" (lines 148-154)
3. `CLAUDE.md`: Remove all OPUS references — "via the OPUS API" (line 25), `import_opus_url` (line 50), "OPUS API calls" (line 58), "OPUS batch job flow" and langchain mention (lines 71-72), `requests, python-dotenv, and optionally langchain` from dependencies (line 79), "OPUS Integration" section (lines 82-84)

## Verify

- `grep -ri opus` across repo returns nothing
- `grep -ri rapidapi` across repo returns nothing
- Remaining 6 MCP tools still function: `get_scene_info`, `create_node`, `execute_houdini_code`, `render_single_view`, `render_quad_views`, `render_specific_camera`
