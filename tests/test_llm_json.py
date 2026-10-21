import unittest

from evoagent.llm import parse_json_object


class ParseJsonObjectTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual({"action": "final"}, parse_json_object('{"action":"final"}'))

    def test_markdown_fence(self):
        content = '```json\n{"findings": []}\n```'
        self.assertEqual({"findings": []}, parse_json_object(content))

    def test_trailing_prose(self):
        content = '{"findings": []}\n\nNo other issues were found.'
        self.assertEqual({"findings": []}, parse_json_object(content))

    def test_leading_prose(self):
        content = 'Here is the review:\n{"findings": []}'
        self.assertEqual({"findings": []}, parse_json_object(content))

    def test_first_object_wins(self):
        content = '{"findings": []}\n{"findings": [{"rule_id": "x"}]}'
        self.assertEqual({"findings": []}, parse_json_object(content))

    def test_braces_inside_strings_are_preserved(self):
        content = '{"evidence": "open(base / user_path)", "fix": "use a map"}'
        self.assertEqual(
            {"evidence": "open(base / user_path)", "fix": "use a map"},
            parse_json_object(content),
        )

    def test_non_object_root_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_json_object('["not", "an", "object"]')

    def test_empty_and_non_text_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_json_object("   ")
        with self.assertRaises(ValueError):
            parse_json_object(None)


if __name__ == "__main__":
    unittest.main()
