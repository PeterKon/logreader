import unittest

from logreader.config import LogreaderConfig


class LogreaderConfigTests(unittest.TestCase):

    def test_defaults_build_the_legacy_search_presets(self):
        config = LogreaderConfig()
        patterns = config.search_patterns()

        self.assertEqual(
            [pattern.key for pattern in patterns],
            ["error_colon", "error", "failed", "fatal"],
        )
        self.assertEqual(patterns[0].context, 3)
        self.assertEqual(patterns[1].context, 0)
        self.assertEqual(patterns[1].excluded_substrings, ("error:",))

    def test_optional_and_custom_patterns_share_context_and_limits(self):
        config = LogreaderConfig(
            context=5,
            generic_context=2,
            limit=10,
            enabled_patterns=("warning", "exception"),
            custom_patterns=(" timeout ",),
            show_separators=False,
            show_generic_separators=True,
        )
        patterns = config.search_patterns()

        self.assertEqual(
            [pattern.key for pattern in patterns],
            ["error_colon", "error", "warning", "exception", "custom_1"],
        )
        self.assertEqual(config.custom_patterns, ("timeout",))
        self.assertEqual(patterns[-1].context, 2)
        self.assertEqual(config.label_for("custom_1"), "timeout")
        self.assertFalse(config.show_separator_for("error_colon"))
        self.assertTrue(config.show_separator_for("warning"))

    def test_invalid_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Context cannot be negative"):
            LogreaderConfig(context=-1)
        with self.assertRaisesRegex(ValueError, "Limit must be positive"):
            LogreaderConfig(limit=0)
        with self.assertRaisesRegex(ValueError, "Unknown optional pattern"):
            LogreaderConfig(enabled_patterns=("unknown",))
        with self.assertRaisesRegex(ValueError, "Custom patterns cannot be empty"):
            LogreaderConfig(custom_patterns=(" ",))


if __name__ == "__main__":
    unittest.main()
