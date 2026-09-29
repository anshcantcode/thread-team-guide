import unittest

from participant.planner import Planner


class MissingFrameToolArgumentGroundingTests(unittest.TestCase):
    @staticmethod
    def decision(args):
        return {
            'intent': 'search flights', 'slots': {},
            'tool_calls': [{'api_name': 'flight_search', 'args': args}],
            'observations': [], 'clarification': None, 'response': None,
        }

    @staticmethod
    def messages(request, frame='missing.png'):
        return [
            {'message_index': 0, 'event_type': 'video_frame',
             'payload': {'image_ref': frame, 'image_unavailable': True}},
            {'message_index': 1, 'event_type': 'user_speech_chunk',
             'payload': {'text': 'Tell me something interesting.'}},
            {'message_index': 2, 'event_type': 'user_speech_chunk',
             'payload': {'text': request}},
        ]

    def validate(self, request, args, frame='missing.png'):
        Planner._validate(
            self.decision(args), [], latest_frame_index=0,
            messages=self.messages(request, frame), current_turn_start=2,
        )

    def test_natural_month_day_year_date_matches_iso_tool_argument(self):
        for request in (
                'Search flights to Paris on September 30, 2026.',
                'Search flights to Paris on 2026-09-30.'):
            with self.subTest(request=request):
                self.validate(request, {'destination': 'Paris', 'date': '2026-09-30'})

    def test_unspoken_query_remains_rejected_after_missing_or_corrupt_frame(self):
        for frame in ('missing.png', 'corrupt.png'):
            with self.subTest(frame=frame), self.assertRaisesRegex(
                    ValueError, 'active request image source is unavailable'):
                self.validate(
                    'Find the manual for the connector from my earlier upload.',
                    {'query': 'LAN'}, frame,
                )


if __name__ == '__main__':
    unittest.main()
