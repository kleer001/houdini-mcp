#!/usr/bin/env bash
# bootstrap.sh — One-command setup for HoudiniMCP (Linux + macOS)
#
# Usage (fresh install):
#   curl -sSL https://raw.githubusercontent.com/kleer001/houdini-mcp/main/bootstrap.sh | bash
#
# Usage (re-run from inside repo):
#   bash bootstrap.sh
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC}   $1"; }
info() { echo -e "${CYAN}[..]${NC}   $1"; }

echo -e "\n${BOLD}=== HoudiniMCP Bootstrap ===${NC}\n"

OS="$(uname -s)"
case "$OS" in
    Linux)  os_label="Linux" ;;
    Darwin) os_label="macOS" ;;
    *)      fail "Unsupported OS: $OS"; exit 1 ;;
esac
info "Detected OS: $os_label"

# -------------------------------------------------------
# Step 1: Check prerequisites
# -------------------------------------------------------
echo -e "\n${BOLD}Step 1: Checking prerequisites${NC}"

# Git (required)
if command -v git &>/dev/null; then
    ok "git found: $(git --version)"
else
    fail "git is not installed. Please install git first."
    exit 1
fi

# Python 3.12+ (required)
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        py_ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [ -n "$py_ver" ]; then
            major="${py_ver%%.*}"
            minor="${py_ver##*.}"
            if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    fi
done

if [ -n "$PYTHON" ]; then
    ok "Python found: $($PYTHON --version)"
else
    fail "Python 3.12+ is required but not found."
    echo "  Install from https://www.python.org/downloads/"
    exit 1
fi

# Houdini (advisory — non-blocking)
HOUDINI_FOUND=false
if command -v houdini &>/dev/null || command -v hython &>/dev/null; then
    HOUDINI_FOUND=true
    ok "Houdini found in PATH"
else
    # Check common install locations
    case "$OS" in
        Linux)
            for d in /opt/hfs*; do
                if [ -d "$d" ]; then
                    HOUDINI_FOUND=true
                    ok "Houdini found: $d"
                    break
                fi
            done
            ;;
        Darwin)
            for d in /Applications/Houdini*; do
                if [ -d "$d" ]; then
                    HOUDINI_FOUND=true
                    ok "Houdini found: $d"
                    break
                fi
            done
            ;;
    esac
fi

if [ "$HOUDINI_FOUND" = false ]; then
    warn "Houdini not detected (setup continues — install Houdini when ready)"
fi

# -------------------------------------------------------
# Step 2: Clone repo (skip if already inside it)
# -------------------------------------------------------
echo -e "\n${BOLD}Step 2: Repository${NC}"

if [ -f "pyproject.toml" ] && [ -f "houdini_mcp_server.py" ]; then
    ok "Already inside houdini-mcp repo — skipping clone"
else
    info "Cloning houdini-mcp..."
    git clone https://github.com/kleer001/houdini-mcp.git
    cd houdini-mcp
    ok "Cloned into $(pwd)"
fi

REPO_DIR="$(pwd)"

# -------------------------------------------------------
# Step 3: Install uv (skip if present)
# -------------------------------------------------------
echo -e "\n${BOLD}Step 3: Package manager (uv)${NC}"

if command -v uv &>/dev/null; then
    ok "uv already installed: $(uv --version)"
else
    info "Installing uv to ~/.local/bin ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the env so uv is available in this session
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        ok "uv installed: $(uv --version)"
    else
        fail "uv installation failed. Install manually: https://docs.astral.sh/uv/"
        exit 1
    fi
fi

# -------------------------------------------------------
# Step 4: Create venv + install deps
# -------------------------------------------------------
echo -e "\n${BOLD}Step 4: Python environment${NC}"

if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    uv venv
fi
ok "Virtual environment: .venv/"

info "Installing dependencies..."
uv sync
ok "Dependencies installed"

# -------------------------------------------------------
# Step 5: Install Houdini plugin
# -------------------------------------------------------
echo -e "\n${BOLD}Step 5: Houdini plugin${NC}"

if [ "$HOUDINI_FOUND" = true ]; then
    info "Installing plugin into Houdini preferences..."
    uv run python scripts/install.py
    ok "Plugin installed"
else
    warn "Houdini not detected — skipping plugin install"
    echo "  Run later: uv run python scripts/install.py"
fi

# -------------------------------------------------------
# Step 6: Fetch Houdini docs
# -------------------------------------------------------
echo -e "\n${BOLD}Step 6: Houdini documentation (offline search)${NC}"

if [ -f "houdini_docs_index.json" ]; then
    ok "Docs index already exists — skipping download"
else
    info "Downloading Houdini docs (~100 MB)..."
    uv run python scripts/fetch_houdini_docs.py
    ok "Documentation index built"
fi

# -------------------------------------------------------
# Step 7: Configure MCP client
# -------------------------------------------------------
echo -e "\n${BOLD}Step 7: MCP client configuration${NC}"

HAVE_CLAUDE_CODE=false
HAVE_CLAUDE_DESKTOP=false

if command -v claude &>/dev/null; then
    HAVE_CLAUDE_CODE=true
    ok "Claude Code CLI detected"
fi

case "$OS" in
    Linux)  desktop_config="$HOME/.config/Claude/claude_desktop_config.json" ;;
    Darwin) desktop_config="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
esac

# Detect Claude Desktop by checking for the app binary
case "$OS" in
    Linux)
        if command -v claude-desktop &>/dev/null || [ -d "/snap/claude-desktop" ]; then
            HAVE_CLAUDE_DESKTOP=true
        fi
        ;;
    Darwin)
        if [ -d "/Applications/Claude.app" ]; then
            HAVE_CLAUDE_DESKTOP=true
        fi
        ;;
esac

# Also count an existing config dir as evidence of Claude Desktop
if [ -d "$(dirname "$desktop_config")" ]; then
    HAVE_CLAUDE_DESKTOP=true
fi

if [ "$HAVE_CLAUDE_DESKTOP" = true ]; then
    ok "Claude Desktop detected"
fi

configure_claude_code() {
    info "Configuring Claude Code MCP server..."
    claude mcp remove houdini 2>/dev/null || true
    claude mcp add --transport stdio --scope user houdini -- \
        uv --directory "$REPO_DIR" run python houdini_mcp_server.py
    ok "Claude Code configured (verify with: claude mcp list)"
}

configure_claude_desktop() {
    info "Configuring Claude Desktop MCP server..."
    "$PYTHON" - "$desktop_config" "$REPO_DIR" <<'PYEOF'
import json, sys, os
config_file, repo_dir = sys.argv[1], sys.argv[2]
config = {}
if os.path.exists(config_file):
    with open(config_file) as f:
        config = json.load(f)
config.setdefault("mcpServers", {})["houdini"] = {
    "command": "uv",
    "args": ["--directory", repo_dir, "run", "python", "houdini_mcp_server.py"]
}
os.makedirs(os.path.dirname(config_file), exist_ok=True)
with open(config_file, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
PYEOF
    ok "Claude Desktop configured: $desktop_config"
}

if [ "$HAVE_CLAUDE_CODE" = true ] && [ "$HAVE_CLAUDE_DESKTOP" = true ]; then
    echo -e "\nDetected both ${BOLD}Claude Code${NC} and ${BOLD}Claude Desktop${NC}."
    echo "  1) Claude Code  (CLI)"
    echo "  2) Claude Desktop (GUI)"
    echo "  3) Both"
    if [ -t 0 ]; then
        read -rp "Configure which? [1/2/3]: " choice
    else
        info "Non-interactive mode — configuring both"
        choice=3
    fi
    case "$choice" in
        1) configure_claude_code ;;
        2) configure_claude_desktop ;;
        3) configure_claude_code; configure_claude_desktop ;;
        *) warn "Invalid choice — skipping MCP configuration" ;;
    esac
elif [ "$HAVE_CLAUDE_CODE" = true ]; then
    configure_claude_code
elif [ "$HAVE_CLAUDE_DESKTOP" = true ]; then
    configure_claude_desktop
else
    warn "Neither Claude Code nor Claude Desktop detected."
    echo "  Install one of:"
    echo "    Claude Code:    https://docs.anthropic.com/en/docs/claude-code"
    echo "    Claude Desktop: https://claude.ai/download"
    echo ""
    echo "  Then re-run this script, or configure manually:"
    echo "    Claude Code:    claude mcp add --transport stdio houdini -- uv --directory \"$REPO_DIR\" run python houdini_mcp_server.py"
    echo "    Claude Desktop: Add to ${desktop_config}:"
    cat <<JSONEOF
{
  "mcpServers": {
    "houdini": {
      "command": "uv",
      "args": [
        "--directory",
        "${REPO_DIR}",
        "run",
        "python",
        "houdini_mcp_server.py"
      ]
    }
  }
}
JSONEOF
fi

# -------------------------------------------------------
# Done
# -------------------------------------------------------
echo -e "\n${BOLD}${GREEN}=== Setup complete! ===${NC}"
echo -e "  Repo:   ${REPO_DIR}"
echo -e "  Venv:   ${REPO_DIR}/.venv/"
if [ "$HOUDINI_FOUND" = false ]; then
    echo -e "  ${YELLOW}Remember to install the Houdini plugin after installing Houdini:${NC}"
    echo -e "    cd ${REPO_DIR} && uv run python scripts/install.py"
fi
echo ""
