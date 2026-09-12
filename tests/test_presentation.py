import unittest

from logreader.core import SearchPattern, analyze_lines
from logreader.presentation import build_category_presentations


class PresentationTests(unittest.TestCase):
    def test_all_scanned_matches_and_context_are_presented_in_both_views(self):
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = analyze_lines(
                    ("ERROR FATAL first", "context", "ERROR FATAL last"),
                    (SearchPattern("error", "ERROR", context=1),
                     SearchPattern("fatal", "FATAL", context=1)),
                    combined=combined, line_offset=20,
                )
                presentations = build_category_presentations(result)
                self.assertEqual(len(presentations), 1 if combined else 2)
                for presentation in presentations:
                    self.assertIs(presentation.excerpts, presentation.result.excerpts)
                    self.assertEqual([line.number for line in presentation.excerpts[0].lines], [21, 22, 23])
                    self.assertEqual(presentation.result.matched_line_count, 2)

    def test_zero_match_categories_remain_in_analysis_without_detail_sections(self):
        result = analyze_lines(("ERROR boom",),
                               (SearchPattern("error", "ERROR"), SearchPattern("fatal", "FATAL")))
        presentations = build_category_presentations(result)
        self.assertEqual([p.key for p in presentations], ["error"])
        self.assertEqual(presentations[0].heading("ERROR"), "ERROR — 1 matches")
        self.assertIn("fatal", result.categories)
