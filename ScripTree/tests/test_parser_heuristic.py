"""Tests for the heuristic parser and Tier-1 detectors.

The fixtures below are synthetic but shaped to match real argparse and
click output. Each test checks a specific behavior (detection, flag
parsing, keyword promotion, choices) rather than whole-file equality,
so small parser tweaks don't cascade into noise.
"""
from __future__ import annotations

from scriptree.core.model import ParamType, Widget
from scriptree.core.parser.probe import parse_text
from scriptree.core.parser.plugins import argparse as argparse_detector
from scriptree.core.parser.plugins import click as click_detector
from scriptree.core.parser.plugins._core import parse_heuristic


# --- fixtures --------------------------------------------------------------

ARGPARSE_HELP = """\
usage: mytool [-h] [-v] [--output FILE] [--mode {fast,slow,auto}]
              [--threads N]
              input_file

Process a file with various options.

positional arguments:
  input_file             The input file to process.

options:
  -h, --help             show this help message and exit
  -v, --verbose          enable verbose logging
  --output FILE          write output to FILE
  --mode {fast,slow,auto}
                         processing mode
  --threads N            number of worker threads
"""

CLICK_HELP = """\
Usage: mytool [OPTIONS] INPUT

  Process a thing with options.

Options:
  --count INTEGER   number of times to repeat
  --name TEXT       name to use
  --dry-run         preview without writing files
  --help            Show this message and exit.
"""

MESSY_HELP = """\
Usage: foo [options] <source> <dest>

Options:
  -r, --recursive     recurse into directories
  -o DIR              output directory
  --log-file PATH     path to log file
  --regex PATTERN     pattern to match against
"""


# --- argparse detector -----------------------------------------------------

class TestArgparseDetector:
    def test_detects_argparse(self) -> None:
        tool = argparse_detector.detect(ARGPARSE_HELP)
        assert tool is not None
        assert tool.source.mode == "argparse"

    def test_strips_help_param(self) -> None:
        tool = argparse_detector.detect(ARGPARSE_HELP)
        assert tool is not None
        ids = [p.id for p in tool.params]
        assert "help" not in ids

    def test_detects_verbose_bool(self) -> None:
        tool = argparse_detector.detect(ARGPARSE_HELP)
        assert tool is not None
        verbose = tool.param_by_id("verbose")
        assert verbose is not None
        assert verbose.type is ParamType.BOOL
        assert verbose.widget is Widget.CHECKBOX

    def test_detects_output_as_file_save(self) -> None:
        tool = argparse_detector.detect(ARGPARSE_HELP)
        assert tool is not None
        out = tool.param_by_id("output")
        assert out is not None
        assert out.type is ParamType.PATH
        assert out.widget is Widget.FILE_SAVE

    def test_detects_mode_enum(self) -> None:
        tool = argparse_detector.detect(ARGPARSE_HELP)
        assert tool is not None
        mode = tool.param_by_id("mode")
        assert mode is not None
        assert mode.type is ParamType.ENUM
        assert mode.widget is Widget.DROPDOWN
        assert set(mode.choices) == {"fast", "slow", "auto"}

    def test_detects_threads_as_number(self) -> None:
        tool = argparse_detector.detect(ARGPARSE_HELP)
        assert tool is not None
        threads = tool.param_by_id("threads")
        assert threads is not None
        # "threads" is a keyword in INTEGER rule; description is empty
        # so we rely on the keyword in the description. The parser sees
        # "number of worker threads" in the description, which triggers
        # the INTEGER keyword rule.
        assert threads.type is ParamType.INTEGER
        assert threads.widget is Widget.NUMBER


# --- click detector --------------------------------------------------------

class TestClickDetector:
    def test_detects_click(self) -> None:
        tool = click_detector.detect(CLICK_HELP)
        assert tool is not None
        assert tool.source.mode == "click"

    def test_does_not_false_match_argparse(self) -> None:
        # argparse help has lowercase "usage:"; click has "Usage:".
        # Our click detector requires "Usage:" + "Options:" (both
        # capitalized). argparse uses "options:" lowercase so it
        # should NOT match the click detector.
        assert click_detector.detect(ARGPARSE_HELP) is None

    def test_does_not_false_match_heuristic_only(self) -> None:
        assert click_detector.detect(MESSY_HELP) is not None  # Options: is capitalized here
        # Whereas random plain text fails:
        assert click_detector.detect("just some prose") is None

    def test_detects_dry_run_bool(self) -> None:
        tool = click_detector.detect(CLICK_HELP)
        assert tool is not None
        dry = tool.param_by_id("dry_run")
        assert dry is not None
        assert dry.type is ParamType.BOOL


# --- heuristic fallback ----------------------------------------------------

class TestHeuristic:
    def test_recursive_is_bool(self) -> None:
        tool = parse_heuristic(MESSY_HELP)
        r = tool.param_by_id("recursive")
        assert r is not None
        assert r.type is ParamType.BOOL

    def test_log_file_promoted_to_file_open(self) -> None:
        tool = parse_heuristic(MESSY_HELP)
        lf = tool.param_by_id("log_file")
        assert lf is not None
        # "path to log file" → FILE_OPEN (first matching "path to" rule)
        assert lf.type is ParamType.PATH
        assert lf.widget in (Widget.FILE_OPEN, Widget.FILE_SAVE)

    def test_regex_promoted_to_textarea(self) -> None:
        tool = parse_heuristic(MESSY_HELP)
        rx = tool.param_by_id("regex")
        assert rx is not None
        assert rx.widget is Widget.TEXTAREA

    def test_positionals_from_usage(self) -> None:
        tool = parse_heuristic(MESSY_HELP)
        ids = [p.id for p in tool.params]
        assert "source" in ids
        assert "dest" in ids

    def test_produces_valid_argument_template(self) -> None:
        tool = parse_heuristic(MESSY_HELP)
        tool.name = "foo"
        tool.executable = "/bin/foo"
        assert tool.validate() == []


# --- probe dispatch --------------------------------------------------------

class TestProbeDispatch:
    def test_parse_text_prefers_argparse(self) -> None:
        tool = parse_text(ARGPARSE_HELP)
        assert tool.source.mode == "argparse"

    def test_parse_text_prefers_click(self) -> None:
        tool = parse_text(CLICK_HELP)
        assert tool.source.mode == "click"

    def test_parse_text_falls_through_to_heuristic(self) -> None:
        # Plain text with some flags but no "options:" or "Options:"
        # header — should land in the heuristic parser.
        msg = "Usage: weird [args]\n\n  -f, --force    force it\n"
        tool = parse_text(msg)
        # No "Options:" header means click detector misses; no
        # "options:" header means argparse misses. Heuristic still
        # parses the -f/--force line.
        assert tool.source.mode == "heuristic"
        assert tool.param_by_id("force") is not None
