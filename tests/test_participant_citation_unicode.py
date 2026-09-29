"""Actual citation comparator witnesses, separate from presentation filtering."""
import unittest

from participant.agent import ParticipantAgent


class UnicodeCitationTests(unittest.TestCase):
    def matches(self, requested, title):
        template = "Reference: {sources.0.title}."
        operation = {"step": {"response_template": template,
            "result_evidence": {"path": "sources.0.title", "contains": requested}},
            "result": {"sources": [{"title": title}]}}
        return ParticipantAgent._source_matches(operation, template)

    def test_distinct_indic_marks_do_not_collapse(self):
        for requested, title in (("कला", "कलि"), ("ध्वनि", "ध्वनी"), ("वायु", "वियु")):
            with self.subTest(requested=requested, title=title):
                self.assertFalse(self.matches(requested, title))
                self.assertFalse(self.matches(title, requested))

    def test_exact_indic_labels_with_marks_remain_valid(self):
        for requested in ("कला", "कलि", "ध्वनि", "ध्वनी", "वायु", "वियु"):
            with self.subTest(requested=requested):
                self.assertTrue(self.matches(requested, requested + " रखरखाव"))

    def test_canonically_equivalent_accents_match(self):
        for requested, title in (("Café", "Cafe\u0301 maintenance"),
                                 ("Cafe\u0301", "CAFÉ maintenance"),
                                 ("Ångström", "A\u030angström maintenance")):
            with self.subTest(requested=requested, title=title):
                self.assertTrue(self.matches(requested, title))

    def test_case_and_separator_boundaries_remain_supported(self):
        self.assertTrue(self.matches("ROTARY-valve", "Rotary_valve maintenance"))
        for requested, title in (("valve", "Valveless pump"), ("कला", "अकला"),
                                 ("", "manual"), ("---", "manual"), ("\u0301", "\u0301")):
            with self.subTest(requested=requested, title=title):
                self.assertFalse(self.matches(requested, title))

    def test_first_reported_noncollision_remains_distinct(self):
        self.assertFalse(self.matches("ध्वनि", "धवनि"))


if __name__ == "__main__":
    unittest.main()
