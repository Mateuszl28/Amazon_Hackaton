import json
import unittest
from pathlib import Path
from unittest import mock

from app import companion, handler, llm, store
from app.fence import build_view, recap_window

TIMELINE = json.loads((Path(__file__).parent / "fixtures" / "mystery.json").read_text())


class RecapWindowTest(unittest.TestCase):
    def test_only_missed_finished_scenes(self):
        view = build_view(TIMELINE, 95)
        self.assertEqual([s["start"] for s in recap_window(view, 35)], [30, 60])


class AskRouteTest(unittest.TestCase):
    def setUp(self):
        self.prompts = []
        self.model_moments = []
        self.model_text = "y"
        self.model_headline = "x"
        self.model_seek = -1

        def fake_complete(system, content, **kw):
            self.prompts.append("\n".join(b.get("text", "") for b in content))
            return json.dumps({"headline": self.model_headline, "answer": self.model_text,
                               "character_id": "c2", "moments": self.model_moments,
                               "seek_to": self.model_seek})

        patches = [
            mock.patch.object(store, "timeline", lambda _id: TIMELINE),
            mock.patch.object(llm, "complete", fake_complete),
            mock.patch.object(llm, "PROVIDER", "bedrock"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def ask(self, **body):
        return handler.route("POST", "/ask", {"title_id": "mystery", **body})

    def test_character_is_reported_under_its_fenced_name(self):
        status, out = self.ask(position_s=70, mode="who")
        self.assertEqual(status, 200)
        self.assertEqual(out["character"]["name"], "Hooded stranger")

    def test_skip_recap_names_the_missed_range(self):
        self.ask(position_s=94, mode="recap", from_s=35)
        self.assertIn("0:35–1:34", self.prompts[-1])
        self.assertNotIn("Tom", self.prompts[-1])
        self.assertNotIn("tom", self.prompts[-1])  # stored ids never reach the model

    def test_future_name_is_redacted_from_the_answer(self):
        # The model "knows" the film (or read the title) and calls him Tom at 1:10 — too early.
        self.model_text = "That is Tom, and Tom looks nervous."
        self.model_headline = "Tom appears"
        _, out = self.ask(position_s=70, mode="who")
        self.assertNotIn("Tom", out["answer"])
        self.assertNotIn("Tom", out["headline"])
        self.assertIn("Hooded stranger", out["answer"])

    def test_already_revealed_name_survives(self):
        self.model_text = "That is Tom, Anna's brother."
        _, out = self.ask(position_s=120, mode="who")
        self.assertIn("Tom", out["answer"])

    def test_jump_target_inside_what_was_seen_is_kept(self):
        self.model_seek = 35
        _, out = self.ask(position_s=70, mode="ask", question="take me back to when they met")
        self.assertEqual(out["seek_to"], 35.0)

    def test_jump_into_the_future_is_dropped(self):
        self.model_seek = 110  # a scene the viewer has not reached
        _, out = self.ask(position_s=70, mode="ask", question="take me to the reveal")
        self.assertIsNone(out["seek_to"])

    def test_no_jump_requested(self):
        _, out = self.ask(position_s=70, mode="who")
        self.assertIsNone(out["seek_to"])

    def test_markers_never_pass_the_fence(self):
        # a model citing the future (100 s, 119 s) must not leak it onto the timeline
        self.model_moments = [10, 45, 100, 119]
        status, out = self.ask(position_s=70, mode="who")
        self.assertEqual(status, 200)
        self.assertEqual(out["markers"], [
            {"t": 10.0, "kind": "moment"},
            {"t": 30.0, "kind": "appearance"},
            {"t": 45.0, "kind": "moment"},
            {"t": 60.0, "kind": "appearance"},
        ])
        self.assertEqual(out["duration_s"], 120)
        self.assertIsNone(out["range"])

    def test_recap_range_is_clamped(self):
        _, out = self.ask(position_s=70, mode="recap", from_s=500)
        self.assertEqual(out["range"], {"from": 70.0, "to": 70.0})

    def test_bad_requests(self):
        self.assertEqual(self.ask(mode="who")[0], 400)
        self.assertEqual(self.ask(position_s=1, mode="dance")[0], 400)

    def test_mock_provider_needs_no_model(self):
        with mock.patch.object(llm, "PROVIDER", "mock"):
            status, out = self.ask(position_s=50, mode="explain")
        self.assertEqual(status, 200)
        self.assertEqual(len(self.prompts), 0)
        self.assertIn("Call me the Stranger.", out["answer"])


if __name__ == "__main__":
    unittest.main()
