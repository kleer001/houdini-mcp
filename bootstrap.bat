@echo off
setlocal enabledelayedexpansion
REM bootstrap.bat — One-command setup for HoudiniMCP (Windows)
REM
REM Usage (fresh install, PowerShell):
REM   powershell -c "irm https://raw.githubusercontent.com/kleer001/houdini-mcp/main/bootstrap.bat -OutFile bootstrap.bat; .\bootstrap.bat"
REM
REM Usage (re-run from inside repo):
REM   bootstrap.bat

echo.
echo === HoudiniMCP Bootstrap ===
echo.

REM -------------------------------------------------------
REM Step 1: Check prerequisites
REM -------------------------------------------------------
echo Step 1: Checking prerequisites

REM Git (required)
where git >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('git --version') do echo [OK]   %%v
) else (
    echo [FAIL] git is not installed. Please install git first.
    echo        https://git-scm.com/download/win
    exit /b 1
)

REM Python 3.12+ (required)
set "PYTHON="
for %%c in (python3 python) do (
    if not defined PYTHON (
        where %%c >nul 2>&1
        if !errorlevel! equ 0 (
            for /f "tokens=*" %%v in ('%%c -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2^>nul') do (
                set "py_ver=%%v"
            )
            if defined py_ver (
                for /f "tokens=1,2 delims=." %%a in ("!py_ver!") do (
                    if %%a geq 3 if %%b geq 12 (
                        set "PYTHON=%%c"
                    )
                )
            )
        )
    )
)

if defined PYTHON (
    for /f "tokens=*" %%v in ('!PYTHON! --version') do echo [OK]   %%v
) else (
    echo [FAIL] Python 3.12+ is required but not found.
    echo        https://www.python.org/downloads/
    exit /b 1
)

REM Houdini (advisory — non-blocking)
set "HOUDINI_FOUND=0"
where houdini >nul 2>&1
if %errorlevel% equ 0 (
    set "HOUDINI_FOUND=1"
    echo [OK]   Houdini found in PATH
) else (
    if exist "C:\Program Files\Side Effects Software\Houdini*" (
        set "HOUDINI_FOUND=1"
        echo [OK]   Houdini found in Program Files
    ) else (
        echo [!!]   Houdini not detected (setup continues — install Houdini when ready^)
    )
)

REM -------------------------------------------------------
REM Step 2: Clone repo (skip if already inside it)
REM -------------------------------------------------------
echo.
echo Step 2: Repository

if exist "pyproject.toml" if exist "houdini_mcp_server.py" (
    echo [OK]   Already inside houdini-mcp repo — skipping clone
    goto :skip_clone
)

echo [..]   Cloning houdini-mcp...
git clone https://github.com/kleer001/houdini-mcp.git
cd houdini-mcp
echo [OK]   Cloned into %cd%

:skip_clone
set "REPO_DIR=%cd%"

REM -------------------------------------------------------
REM Step 3: Install uv (skip if present)
REM -------------------------------------------------------
echo.
echo Step 3: Package manager (uv)

where uv >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('uv --version') do echo [OK]   uv already installed: %%v
) else (
    echo [..]   Installing uv...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    REM Refresh PATH to pick up uv
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%v in ('uv --version') do echo [OK]   uv installed: %%v
    ) else (
        echo [FAIL] uv installation failed. Install manually: https://docs.astral.sh/uv/
        exit /b 1
    )
)

REM -------------------------------------------------------
REM Step 4: Create venv + install deps
REM -------------------------------------------------------
echo.
echo Step 4: Python environment

if not exist ".venv" (
    echo [..]   Creating virtual environment...
    uv venv
)
echo [OK]   Virtual environment: .venv\

echo [..]   Installing dependencies...
uv sync
echo [OK]   Dependencies installed

REM -------------------------------------------------------
REM Step 5: Install Houdini plugin
REM -------------------------------------------------------
echo.
echo Step 5: Houdini plugin

if %HOUDINI_FOUND% equ 1 (
    echo [..]   Installing plugin into Houdini preferences...
    uv run python scripts/install.py
    echo [OK]   Plugin installed
) else (
    echo [!!]   Houdini not detected — skipping plugin install
    echo        Run later: uv run python scripts/install.py
)

REM -------------------------------------------------------
REM Step 6: Fetch Houdini docs
REM -------------------------------------------------------
echo.
echo Step 6: Houdini documentation (offline search)

if exist "houdini_docs_index.json" (
    echo [OK]   Docs index already exists — skipping download
) else (
    echo [..]   Downloading Houdini docs (~100 MB)...
    uv run python scripts/fetch_houdini_docs.py
    echo [OK]   Documentation index built
)

REM -------------------------------------------------------
REM Step 7: Print Claude Desktop config
REM -------------------------------------------------------
echo.
echo Step 7: Claude Desktop configuration

REM Build forward-slash path for JSON
set "JSON_PATH=%REPO_DIR:\=/%"

echo.
echo Add this to your Claude Desktop config file:
echo   %APPDATA%\Claude\claude_desktop_config.json
echo.
echo {
echo   "mcpServers": {
echo     "houdini": {
echo       "command": "uv",
echo       "args": [
echo         "--directory",
echo         "%JSON_PATH%",
echo         "run",
echo         "python",
echo         "houdini_mcp_server.py"
echo       ]
echo     }
echo   }
echo }

echo.
echo === Setup complete! ===
echo   Repo:   %REPO_DIR%
echo   Venv:   %REPO_DIR%\.venv\
if %HOUDINI_FOUND% equ 0 (
    echo   Remember to install the Houdini plugin after installing Houdini:
    echo     cd %REPO_DIR% ^& uv run python scripts/install.py
)
echo.
