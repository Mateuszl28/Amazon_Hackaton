import json
import unittest
from pathlib import Path

from app.fence import build_view

TIMELINE = json.loads((Path(__file__).parent / "fixtures" / "mystery.json").read_text())


class SpoilerFenceTest(unittest.TestCase):
    def test_nothing_after_position_reaches_the_prompt(self):
        prompt = build_view(TIMELINE, 70).to_prompt()
        self.assertNotIn("Tom", prompt)
        self.assertNotIn("brother", prompt)
        self.assertIn("Hooded stranger", prompt)

    def test_unfinished_scene_summary_is_hidden(self):
        view = build_view(TIMELINE, 45)
        self.assertEqual([s["start"] for s in view.segments], [0])

    def test_character_on_screen_is_known_before_scene_ends(self):
        names = [c.name for c in build_view(TIMELINE, 35).characters]
        self.assertEqual(names, ["Anna", "Hooded stranger"])

    def test_reveal_after_it_happens(self):
        view = build_view(TIMELINE, 120)
        tom = next(c for c in view.characters if c.id == "tom")
        self.assertEqual(tom.name, "Tom")
        self.assertIn("Anna's brother.", [f["text"] for f in tom.facts])

    def test_live_dialogue_window(self):
        view = build_view(TIMELINE, 100)
        self.assertEqual([c["text"] for c in view.live_dialogue],
                         ["Call me the Stranger.", "I am your brother, Tom."])


if __name__ == "__main__":
    unittest.main()
