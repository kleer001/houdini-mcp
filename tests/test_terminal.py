"""Tests for claude_terminal.py — ANSI stripping and constants."""
import ast
import re
import textwrap

import pytest


# We can't import claude_terminal directly (needs PySide2), so test the pure
# functions via AST extraction or regex reimplementation.


def _extract_strip_ansi_regex():
    """Extract the ANSI regex pattern from the source via AST."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "src" / "houdinimcp" / "claude_terminal.py"
    source = src.read_text()
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
    """Verify constants are defined correctly in the source."""

    def setup_method(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "src" / "houdinimcp" / "claude_terminal.py"
        self._source = src.read_text()

    def test_themes_defined(self):
        assert "THEMES" in self._source
        assert '"dark"' in self._source
        assert '"light"' in self._source

    def test_font_size_constants(self):
        assert "DEFAULT_FONT_SIZE" in self._source
        assert "MIN_FONT_SIZE" in self._source
        assert "MAX_FONT_SIZE" in self._source

    def test_scrollback_constant(self):
        assert "DEFAULT_SCROLLBACK" in self._source

    def test_classes_defined(self):
        assert "class TerminalTab" in self._source
        assert "class ClaudeTerminalWidget" in self._source
        assert "class ConnectionStatusLED" in self._source

    def test_create_panel_function(self):
        assert "def create_panel" in self._source
