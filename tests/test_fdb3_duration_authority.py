"""Independent duration-binding controls; no model or benchmark fixtures."""
import unittest

from participant.agent import _has_exact_field_value, _explicit_numeric_field_values


class DurationAuthorityTests(unittest.TestCase):
    def test_literal_duration_matches_its_exact_unit(self):
        for unit, amount in [('seconds', 83), ('minutes', 19), ('hours', 3), ('milliseconds', 241)]:
            with self.subTest(unit=unit):
                command = f'set a timer for {amount} {unit} called millet'
                self.assertTrue(_has_exact_field_value(unit, amount, command))
                self.assertEqual(_explicit_numeric_field_values(unit, command), {amount})

    def test_no_conversion_inference_or_unrelated_number(self):
        for command in ['set a timer for 2 minutes called millet',
                        'set a timer called millet 120',
                        'set a timer with 120 seconds remaining',
                        'set a timer for 120.5 seconds called millet',
                        'set a timer for 1200 seconds called millet',
                        'set a timer for 120 seconds=9',
                        'set a timer for 120 seconds or 90 called millet',
                        'set a timer for 120 seconds plus 5 called millet',
                        'set a timer for 120 seconds plus five called millet',
                        'set a timer for 120 seconds called millet but double the duration',
                        'set a timer for 120 seconds called millet or make it ninety',
                        'set a timer for 120 seconds called millet plus five seconds',
                        'set a timer called millet and roast the grain for 120 seconds',
                        'set a timer called millet with the oven running for 120 seconds',
                        'set a timer for 120 seconds and warm up for 4 minutes']:
            with self.subTest(command=command):
                self.assertFalse(_has_exact_field_value('seconds', 120, command))

    def test_no_nested_field_or_arbitrary_numeric_field_inference(self):
        command = 'set a timer for 83 seconds called millet'
        self.assertFalse(_has_exact_field_value('duration.seconds', 83, command))
        self.assertFalse(_has_exact_field_value('price', 83, command))

    def test_explicit_conflict_remains_a_rejection(self):
        self.assertFalse(_has_exact_field_value('seconds', 83, 'set a timer for 83 seconds with seconds=29'))
        self.assertTrue(_has_exact_field_value('seconds', 83, 'set a timer seconds=83'))


if __name__ == '__main__':
    unittest.main()
