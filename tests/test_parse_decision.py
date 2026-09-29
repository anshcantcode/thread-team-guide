"""A repeated JSON key is fatal except inside planner memory (public case 65, all runs)."""
import unittest

from thread_agent.fdb3 import parse_decision


class ParseDecisionTest(unittest.TestCase):
    def test_repeated_key_in_slots_drops_only_the_memory(self):
        content = ('{"intent":"update_search_filter","slots":{"filter_name":"max_price","value":"3000",'
                   '"filter_name":"bedrooms","value":"3"},"tool_calls":[{"api_name":"update_search_filter",'
                   '"args":{"filter_name":"max_price","value":"3000"},"authorization":{"clauses":["2.1"]}}],'
                   '"response":null}')
        decision, dropped = parse_decision(content)
        self.assertTrue(dropped)
        self.assertEqual(decision["slots"], {})
        self.assertEqual(decision["tool_calls"][0]["args"], {"filter_name": "max_price", "value": "3000"})

    def test_repeated_key_anywhere_else_is_fatal(self):
        for content in ('{"intent":"x","slots":{},"tool_calls":[{"api_name":"a","args":{"k":1,"k":2}}]}',
                        '{"intent":"x","intent":"y","slots":{},"tool_calls":[]}',
                        '{"intent":"x","slots":{},"tool_calls":[{"api_name":"a","api_name":"b","args":{}}]}',
                        '{"intent":"x","slots":{},"tool_calls":[{"api_name":"a","args":{},'
                        '"authorization":{"clauses":["0.0"],"clauses":["1.0"]}}]}'):
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    parse_decision(content)

    def test_clean_decision_unchanged(self):
        decision, dropped = parse_decision('{"intent":"x","slots":{"a":{"b":1}},"tool_calls":[]}')
        self.assertFalse(dropped)
        self.assertEqual(decision["slots"], {"a": {"b": 1}})


if __name__ == "__main__":
    unittest.main()
