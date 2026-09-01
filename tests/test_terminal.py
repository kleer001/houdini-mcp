"""Tests for claude_terminal.py — ANSI stripping and terminal launcher."""
import re

import pytest


# We can't import claude_terminal directly (needs PySide2), so test the pure
# functions via AST extraction or regex reimplementation.


def _extract_strip_ansi_regex():
    """Extract the ANSI regex pattern from the source via AST."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "src" / "houdinimcp" / "claude_terminal.py"
    source = src.read_text(encoding="utf-8")
    # Find the _ANSI_RE pattern string
    match = re.search(r"_ANSI_RE\s*=\s*re\.compile\(r'(.+?)'\)", source)
    assert match, "Could not find _ANSI_RE in claude_terminal.py"
    return re.compile(match.group(1))


class TestStripAnsi:
    def setup_method(self):
        self._ansi_re = _extract_strip_ansi_regex()

    def _strip(self, text):
        return self._ansi_re.sub('', text)

    def test_plain_text_unchanged(self):
        assert self._strip("hello world") == "hello world"

    def test_removes_color_codes(self):
        assert self._strip("\x1b[31mred text\x1b[0m") == "red text"

    def test_removes_bold(self):
        assert self._strip("\x1b[1mbold\x1b[0m") == "bold"

    def test_removes_cursor_movement(self):
        assert self._strip("\x1b[2Jclear\x1b[H") == "clear"

    def test_removes_osc_sequences(self):
        assert self._strip("\x1b]0;window title\x07text") == "text"

    def test_empty_string(self):
        assert self._strip("") == ""

    def test_multiple_sequences(self):
        result = self._strip("\x1b[32mgreen\x1b[0m and \x1b[34mblue\x1b[0m")
        assert result == "green and blue"


class TestTerminalConstants:
    """Verify key elements are defined correctly in the source."""

    def setup_method(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "src" / "houdinimcp" / "claude_terminal.py"
        self._source = src.read_text(encoding="utf-8")

    def test_classes_defined(self):
        assert "class ClaudeTerminalWidget" in self._source

    def test_create_panel_function(self):
        assert "def create_panel" in self._source

    def test_is_windows_defined(self):
        assert "_IS_WINDOWS" in self._source


class TestTerminalLauncher:
    """Verify terminal launcher patterns in the source."""

    def setup_method(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "src" / "houdinimcp" / "claude_terminal.py"
        self._source = src.read_text(encoding="utf-8")

    def test_detect_terminal_function(self):
        assert "def _detect_terminal" in self._source

    def test_build_houdini_env_function(self):
        assert "def _build_houdini_env" in self._source

    def test_build_system_prompt_function(self):
        assert "def _build_system_prompt" in self._source

    def test_launch_in_terminal_function(self):
        assert "def _launch_in_terminal" in self._source

    def test_shutil_which_used(self):
        assert "shutil.which" in self._source

    def test_subprocess_popen_used(self):
        assert "subprocess.Popen" in self._source

    def test_terminal_names_linux(self):
        """Common Linux terminal emulators should be in the detection list."""
        assert "gnome-terminal" in self._source
        assert "konsole" in self._source
        assert "xterm" in self._source

    def test_terminal_names_windows(self):
        """Windows terminals should be in the detection list."""
        assert "powershell" in self._source

    def test_append_system_prompt_used(self):
        """System prompt should be passed to claude CLI."""
        assert "append-system-prompt" in self._source

    def test_term_env_set(self):
        """TERM=xterm-256color should be set for proper terminal detection."""
        assert "xterm-256color" in self._source

    def test_claude_terminal_override_env(self):
        """CLAUDE_TERMINAL env var should be respected for terminal override."""
        assert "CLAUDE_TERMINAL" in self._source
