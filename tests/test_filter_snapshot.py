import json
import unittest
from dataclasses import replace

from logreader.config import LogreaderConfig, MAX_CONTEXT, MAX_LINES_SCANNED, PATTERN_KEYS
from logreader.filter_snapshot import FilterSnapshot, PatternSnapshot


class FilterSnapshotTests(unittest.TestCase):
    def test_defaults_match_the_app_and_snapshot_is_independent_of_profile_metadata(self):
        snapshot = FilterSnapshot()
        config = LogreaderConfig()
        for name in ("enabled_patterns", "context", "max_lines_scanned", "combined_view", "separate_entries"):
            self.assertEqual(getattr(snapshot, name), getattr(config, name))
        data = json.loads(json.dumps(snapshot.to_dict()))
        self.assertEqual(FilterSnapshot.from_dict(data), snapshot)
        self.assertEqual(set(data), {
            "version", "enabled_patterns", "custom_patterns", "regex_patterns", "context",
            "max_lines_scanned", "combined_view", "separate_entries",
        })

    def test_entries_keep_order_duplicates_unicode_and_disabled_options(self):
        entries = [PatternSnapshot("blå", match_case=True),
                   PatternSnapshot("blå", enabled=False, exclude=True),
                   PatternSnapshot("other", enabled=False, exclusive=True, match_case=True)]
        snapshot = FilterSnapshot(enabled_patterns=list(reversed(PATTERN_KEYS)), custom_patterns=entries)
        entries.clear()
        data = snapshot.to_dict()
        self.assertEqual(FilterSnapshot.from_dict(json.loads(json.dumps(data))), snapshot)
        self.assertEqual(snapshot.enabled_patterns, PATTERN_KEYS)
        self.assertEqual([entry.text for entry in snapshot.custom_patterns], ["blå", "blå", "other"])
        data["custom_patterns"][0]["text"] = "changed"
        data["enabled_patterns"].clear()
        self.assertEqual(snapshot.custom_patterns[0].text, "blå")
        self.assertEqual(snapshot.enabled_patterns, PATTERN_KEYS)

    def test_rejects_incomplete_unknown_or_wrongly_typed_snapshot_data(self):
        cases = (
            ("version", True, "version"), ("version", 2, "version"),
            ("context", True, "Context"), ("context", -1, "Context"),
            ("context", MAX_CONTEXT + 1, "Context"), ("context", 2.5, "Context"),
            ("max_lines_scanned", 0, "Max lines"), ("max_lines_scanned", "20", "Max lines"),
            ("max_lines_scanned", MAX_LINES_SCANNED + 1, "Max lines"),
            ("combined_view", 1, "Combined view"), ("separate_entries", "false", "Line-spacing"),
            ("enabled_patterns", "error", "list"), ("enabled_patterns", [{}], "identifiers"),
            ("enabled_patterns", ["missing"], "Unknown patterns"),
            ("enabled_patterns", ["error", "error"], "duplicate"),
            ("custom_patterns", None, "list"), ("regex_patterns", {}, "list"),
            ("custom_patterns", ["text"], "entry 1"),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                data = FilterSnapshot().to_dict()
                data[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    FilterSnapshot.from_dict(data)
        data = FilterSnapshot().to_dict()
        del data["context"]
        with self.assertRaisesRegex(ValueError, "missing: context"):
            FilterSnapshot.from_dict(data)
        data = FilterSnapshot().to_dict()
        data["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "Unknown.*unexpected"):
            FilterSnapshot.from_dict(data)
        with self.assertRaisesRegex(ValueError, "must be an object"):
            FilterSnapshot.from_dict([])

    def test_rejects_invalid_entry_options(self):
        for field, value, message in (
            ("text", "  ", "non-empty"), ("text", 42, "non-empty"),
            ("text", "a\nb", "one line"), ("enabled", "false", "true or false"),
            ("match_case", 1, "true or false"), ("exclude", None, "true or false"),
            ("exclusive", [], "true or false"),
            ("name", 7, "name"), ("name", "x\u2029y", "one line"),
        ):
            with self.subTest(field=field, value=value):
                data = PatternSnapshot("valid").to_dict()
                data[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    PatternSnapshot.from_dict(data)
        with self.assertRaisesRegex(ValueError, "both excluded and exclusive"):
            PatternSnapshot("valid", enabled=False, exclude=True, exclusive=True)
        data = PatternSnapshot("valid").to_dict()
        del data["enabled"]
        with self.assertRaisesRegex(ValueError, "missing: enabled"):
            PatternSnapshot.from_dict(data)

    def test_standalone_snapshot_preserves_unfinished_regex_for_future_sessions(self):
        snapshot = FilterSnapshot(regex_patterns=(PatternSnapshot("["), PatternSnapshot("(", enabled=False)))
        self.assertEqual(FilterSnapshot.from_dict(snapshot.to_dict()), snapshot)

    def test_limits_and_empty_selections_are_preserved(self):
        for context, limit in ((0, 1), (MAX_CONTEXT, MAX_LINES_SCANNED)):
            with self.subTest(context=context, limit=limit):
                snapshot = replace(FilterSnapshot(), enabled_patterns=(), context=context,
                                   max_lines_scanned=limit, combined_view=False, separate_entries=False)
                self.assertEqual(FilterSnapshot.from_dict(snapshot.to_dict()), snapshot)
