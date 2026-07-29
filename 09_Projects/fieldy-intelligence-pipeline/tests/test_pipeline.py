import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from ai_sorter import normalise
from fieldy import item_list, transcript
from run import run_slot


class Tests(unittest.TestCase):
    def test_fieldy_shapes(self):
        self.assertEqual(item_list({"items": [{"id": "1"}]}, "conversations"), [{"id": "1"}])
        self.assertEqual(item_list({"data": {"conversations": [{"id": "2"}]}}, "conversations"), [{"id": "2"}])

    def test_schedule(self):
        tz = ZoneInfo("America/St_Johns")
        self.assertEqual(run_slot(datetime(2026, 7, 29, 8, 10, tzinfo=tz)), "Morning")
        self.assertEqual(run_slot(datetime(2026, 7, 29, 12, 40, tzinfo=tz)), "Midday")
        self.assertIsNone(run_slot(datetime(2026, 7, 29, 10, 0, tzinfo=tz)))

    def test_transcript_filter(self):
        segs = [{"conversationId": "a", "speakerName": "Chris", "text": "Hello"}, {"conversationId": "b", "text": "Ignore"}]
        self.assertEqual(transcript(segs, "a"), "Chris: Hello")

    def test_normalise(self):
        x = normalise({"meeting_type": "Bad", "tags": ["Talent Attraction"], "summary": "S", "key_decisions": [], "participants": [], "organizations": [], "needs_chris_review": False, "actions": [], "signals": []})
        self.assertEqual(x["meeting_type"], "Other")
        self.assertEqual(x["tags"], ["Talent Attraction"])


if __name__ == "__main__":
    unittest.main()
