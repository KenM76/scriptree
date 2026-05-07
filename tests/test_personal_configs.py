"""Tests for personal vs shared configurations.

Covers:
- Configuration.storage field round-trip
- ConfigurationSet.source_filename / source_locations
- personal_configs_path naming scheme (.NNN-scriptree.configs.json)
- find_personal_config_candidates (globs, filters by stem)
- load_personal_configs_for (filename match + location match)
- save_personal_configs (populates source fields)
- next_available_suffix_num
- add_location_to_personal
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scriptree.core.configs import (
    Configuration,
    ConfigurationSet,
    add_location_to_personal,
    configs_from_dict,
    configs_to_dict,
    find_personal_config_candidates,
    load_personal_configs_for,
    next_available_suffix_num,
    personal_configs_path,
    save_personal_configs,
    save_personal_configs_at,
)


class TestStorageField:
    def test_default_shared(self):
        c = Configuration(name="default")
        assert c.storage == "shared"

    def test_round_trip_shared_not_emitted(self):
        c = Configuration(name="x", storage="shared")
        s = ConfigurationSet(active="x", configurations=[c])
        d = configs_to_dict(s)
        # "shared" is the default, should be omitted.
        assert "storage" not in d["configurations"][0]

    def test_round_trip_personal_emitted(self):
        c = Configuration(name="x", storage="personal")
        s = ConfigurationSet(active="x", configurations=[c])
        d = configs_to_dict(s)
        assert d["configurations"][0]["storage"] == "personal"

    def test_round_trip_personal_preserved(self):
        c = Configuration(name="x", storage="personal")
        s = ConfigurationSet(active="x", configurations=[c])
        d = configs_to_dict(s)
        s2 = configs_from_dict(d)
        assert s2.configurations[0].storage == "personal"


class TestSourceFields:
    def test_default_empty(self):
        s = ConfigurationSet()
        assert s.source_filename == ""
        assert s.source_locations == []

    def test_non_empty_round_trip(self):
        s = ConfigurationSet(
            active="default",
            configurations=[Configuration(name="default")],
            source_filename="robocopy.scriptree",
            source_locations=[r"C:\tools"],
        )
        d = configs_to_dict(s)
        assert d["source_filename"] == "robocopy.scriptree"
        assert d["source_locations"] == [r"C:\tools"]
        s2 = configs_from_dict(d)
        assert s2.source_filename == "robocopy.scriptree"
        assert s2.source_locations == [r"C:\tools"]

    def test_empty_not_emitted(self):
        s = ConfigurationSet(
            active="x",
            configurations=[Configuration(name="x")],
        )
        d = configs_to_dict(s)
        assert "source_filename" not in d
        assert "source_locations" not in d


class TestPersonalConfigsPath:
    def test_suffix_zero_format(self, tmp_path: Path):
        p = personal_configs_path(
            "robocopy.scriptree", suffix_num=0, personal_dir=tmp_path
        )
        assert p.name == "robocopy.000-scriptree.configs.json"

    def test_suffix_seven_zero_padded(self, tmp_path: Path):
        p = personal_configs_path(
            "robocopy.scriptree", suffix_num=7, personal_dir=tmp_path
        )
        assert p.name == "robocopy.007-scriptree.configs.json"

    def test_suffix_hundred(self, tmp_path: Path):
        p = personal_configs_path(
            "robocopy.scriptree", suffix_num=123, personal_dir=tmp_path
        )
        assert p.name == "robocopy.123-scriptree.configs.json"

    def test_tree_uses_tree_suffix(self, tmp_path: Path):
        p = personal_configs_path(
            "mytree.scriptreetree", suffix_num=5, personal_dir=tmp_path
        )
        assert p.name == "mytree.005-scriptreetree.treeconfigs.json"


class TestFindPersonalConfigCandidates:
    def test_empty_dir_returns_empty(self, tmp_path: Path):
        cands = find_personal_config_candidates(
            "robocopy.scriptree", personal_dir=tmp_path
        )
        assert cands == []

    def test_matches_stem_sorted_by_suffix(self, tmp_path: Path):
        (tmp_path / "robocopy.000-scriptree.configs.json").touch()
        (tmp_path / "robocopy.002-scriptree.configs.json").touch()
        (tmp_path / "robocopy.001-scriptree.configs.json").touch()
        (tmp_path / "robocopy.010-scriptree.configs.json").touch()
        cands = find_personal_config_candidates(
            "robocopy.scriptree", personal_dir=tmp_path
        )
        nums = [c.name.split(".")[1].split("-")[0] for c in cands]
        assert nums == ["000", "001", "002", "010"]

    def test_ignores_other_stems(self, tmp_path: Path):
        (tmp_path / "robocopy.000-scriptree.configs.json").touch()
        (tmp_path / "ffmpeg.000-scriptree.configs.json").touch()
        cands = find_personal_config_candidates(
            "robocopy.scriptree", personal_dir=tmp_path
        )
        assert len(cands) == 1
        assert "robocopy" in cands[0].name

    def test_ignores_shared_sidecar(self, tmp_path: Path):
        (tmp_path / "robocopy.scriptree.configs.json").touch()
        cands = find_personal_config_candidates(
            "robocopy.scriptree", personal_dir=tmp_path
        )
        assert cands == []


class TestNextAvailableSuffixNum:
    def test_no_files_returns_zero(self, tmp_path: Path):
        assert next_available_suffix_num(
            "robocopy.scriptree", personal_dir=tmp_path
        ) == 0

    def test_increments_from_max(self, tmp_path: Path):
        (tmp_path / "robocopy.000-scriptree.configs.json").touch()
        (tmp_path / "robocopy.002-scriptree.configs.json").touch()
        assert next_available_suffix_num(
            "robocopy.scriptree", personal_dir=tmp_path
        ) == 3

    def test_ignores_other_stems(self, tmp_path: Path):
        (tmp_path / "ffmpeg.005-scriptree.configs.json").touch()
        assert next_available_suffix_num(
            "robocopy.scriptree", personal_dir=tmp_path
        ) == 0


class TestSavePersonalConfigs:
    def test_populates_source_fields(self, tmp_path: Path):
        tool_dir = tmp_path / "tools"
        tool_dir.mkdir()
        tool_path = tool_dir / "robocopy.scriptree"
        tool_path.touch()
        personal_dir = tmp_path / "user_configs"
        personal_dir.mkdir()

        cfg_set = ConfigurationSet(
            active="default",
            configurations=[Configuration(name="default")],
        )
        saved = save_personal_configs(
            tool_path, cfg_set, suffix_num=0, personal_dir=personal_dir,
        )
        assert saved.exists()
        assert cfg_set.source_filename == "robocopy.scriptree"
        assert str(tool_dir.resolve()) in cfg_set.source_locations

        # Reload and verify fields persisted.
        data = json.loads(saved.read_text(encoding="utf-8"))
        assert data["source_filename"] == "robocopy.scriptree"
        assert str(tool_dir.resolve()) in data["source_locations"]


class TestLoadPersonalConfigsFor:
    def _make_personal_file(
        self, personal_dir: Path, tool_name: str, suffix: int,
        source_filename: str, source_locations: list[str],
        configs: list[str] | None = None,
    ) -> Path:
        cfg_set = ConfigurationSet(
            active=(configs or ["default"])[0],
            configurations=[
                Configuration(name=n) for n in (configs or ["default"])
            ],
            source_filename=source_filename,
            source_locations=source_locations,
        )
        path = personal_dir / (
            f"{Path(tool_name).stem}.{suffix:03d}-scriptree.configs.json"
        )
        path.write_text(
            json.dumps(configs_to_dict(cfg_set), indent=2),
            encoding="utf-8",
        )
        return path

    def test_no_candidates_returns_none_none(self, tmp_path: Path):
        tool_path = tmp_path / "robocopy.scriptree"
        tool_path.touch()
        personal_dir = tmp_path / "pd"
        personal_dir.mkdir()
        cfg_set, cands = load_personal_configs_for(
            tool_path, personal_dir=personal_dir,
        )
        assert cfg_set is None
        assert cands == []

    def test_exact_location_match(self, tmp_path: Path):
        tool_dir = tmp_path / "tools"
        tool_dir.mkdir()
        tool_path = tool_dir / "robocopy.scriptree"
        tool_path.touch()
        personal_dir = tmp_path / "pd"
        personal_dir.mkdir()
        self._make_personal_file(
            personal_dir, "robocopy.scriptree", 0,
            source_filename="robocopy.scriptree",
            source_locations=[str(tool_dir.resolve())],
        )
        cfg_set, cands = load_personal_configs_for(
            tool_path, personal_dir=personal_dir,
        )
        assert cfg_set is not None
        assert cands == []

    def test_different_location_returns_candidates(self, tmp_path: Path):
        tool_dir = tmp_path / "tools"
        tool_dir.mkdir()
        other_dir = tmp_path / "somewhere_else"
        tool_path = tool_dir / "robocopy.scriptree"
        tool_path.touch()
        personal_dir = tmp_path / "pd"
        personal_dir.mkdir()
        self._make_personal_file(
            personal_dir, "robocopy.scriptree", 0,
            source_filename="robocopy.scriptree",
            source_locations=[str(other_dir)],
        )
        cfg_set, cands = load_personal_configs_for(
            tool_path, personal_dir=personal_dir,
        )
        assert cfg_set is None
        assert len(cands) == 1

    def test_wrong_filename_excluded(self, tmp_path: Path):
        """A file named robocopy.000-scriptree with a different
        source_filename inside should not be considered a match."""
        tool_path = tmp_path / "tools" / "robocopy.scriptree"
        tool_path.parent.mkdir(parents=True)
        tool_path.touch()
        personal_dir = tmp_path / "pd"
        personal_dir.mkdir()
        # Create a file whose filename stem MATCHES but source_filename DOESN'T.
        self._make_personal_file(
            personal_dir, "robocopy.scriptree", 0,
            source_filename="something_else.scriptree",  # mismatch
            source_locations=[str(tool_path.parent)],
        )
        cfg_set, cands = load_personal_configs_for(
            tool_path, personal_dir=personal_dir,
        )
        assert cfg_set is None
        assert cands == []


class TestAddLocationToPersonal:
    def test_append_new_location(self, tmp_path: Path):
        cfg_set = ConfigurationSet(
            active="default",
            configurations=[Configuration(name="default")],
            source_filename="robocopy.scriptree",
            source_locations=[r"C:\A"],
        )
        p = tmp_path / "x.scriptree.000-scriptree.configs.json"
        save_personal_configs_at(p, cfg_set)
        add_location_to_personal(p, r"C:\B")
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["source_locations"] == [r"C:\A", r"C:\B"]

    def test_replace_with_single(self, tmp_path: Path):
        cfg_set = ConfigurationSet(
            active="default",
            configurations=[Configuration(name="default")],
            source_filename="robocopy.scriptree",
            source_locations=[r"C:\A", r"C:\B"],
        )
        p = tmp_path / "x.scriptree.000-scriptree.configs.json"
        save_personal_configs_at(p, cfg_set)
        add_location_to_personal(p, r"C:\C", replace=True)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["source_locations"] == [r"C:\C"]

    def test_append_skips_duplicate(self, tmp_path: Path):
        cfg_set = ConfigurationSet(
            active="default",
            configurations=[Configuration(name="default")],
            source_filename="robocopy.scriptree",
            source_locations=[r"C:\A"],
        )
        p = tmp_path / "x.scriptree.000-scriptree.configs.json"
        save_personal_configs_at(p, cfg_set)
        add_location_to_personal(p, r"C:\A")  # already present
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["source_locations"] == [r"C:\A"]
