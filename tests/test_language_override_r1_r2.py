"""Audit §14 R1 / R2 -- reply-language precedence.

R1: a stored language_override yields when the customer's script clearly
    differs (Devanagari after "reply in English" -> Hindi).
R2: the low-signal check matches the WHOLE message, not a prefix
    ("ok, what is your return policy" is prose, not an ack).
Plus Hinglish and mixed-script cases around both.
"""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.processors.classifier import (  # noqa: E402
    _is_low_language_signal,
    _store_language,
)


def run(profile, label, text):
    _store_language(profile, label, text)
    return profile


class R1OverrideYieldsToScript(unittest.TestCase):
    def test_r1_devanagari_after_reply_in_english_is_hindi(self):
        p = run({"language": "en", "language_override": "en"}, "hi", "मुझे सोने की अंगूठी चाहिए")
        self.assertEqual(p["language"], "hi")
        self.assertNotIn("language_override", p)  # dropped, not skipped once

    def test_after_yielding_the_next_english_message_follows_its_label(self):
        p = run({"language": "en", "language_override": "en"}, "hi", "मुझे सोने की अंगूठी चाहिए")
        run(p, "en", "show me gold rings under 50000 please")
        self.assertEqual(p["language"], "en")

    def test_devanagari_without_a_label_still_hindi(self):
        p = run({"language_override": "en"}, None, "सोने की अंगूठी दिखाओ")
        self.assertEqual(p["language"], "hi")

    def test_other_script_after_other_override(self):
        p = run({"language_override": "hi"}, "gu", "મને સોનાની વીંટી બતાવો")
        self.assertEqual(p["language"], "gu")

    def test_same_script_keeps_the_override(self):
        # Devanagari after "reply in Marathi": same script, keep Marathi.
        p = run({"language_override": "mr"}, "hi", "मला सोन्याची अंगठी दाखवा")
        self.assertEqual(p["language"], "mr")
        self.assertEqual(p["language_override"], "mr")

    def test_hinglish_keeps_an_english_override(self):
        # Romanized Hindi is still Latin script: the explicit request stands.
        p = run({"language_override": "en"}, "hi-Latn", "mujhe sone ki ring chahiye")
        self.assertEqual(p["language"], "en")
        self.assertEqual(p["language_override"], "en")

    def test_english_prose_keeps_a_hindi_override(self):
        p = run({"language_override": "hi"}, "en", "show me gold rings please")
        self.assertEqual(p["language"], "hi")

    def test_mixed_script_mostly_devanagari_yields(self):
        p = run({"language_override": "en"}, "hi", "मुझे यह ring पसंद है, इसकी कीमत बताइए")
        self.assertEqual(p["language"], "hi")

    def test_mixed_script_one_hindi_word_keeps_english(self):
        p = run({"language_override": "en"}, "en", "I want a gold ring for my दादी birthday")
        self.assertEqual(p["language"], "en")
        self.assertEqual(p["language_override"], "en")

    def test_request_in_the_same_message_wins_over_the_script(self):
        # A request made in this very message is honoured even if most of the
        # message is Devanagari.
        p = run({}, "hi", "मुझे अंगूठी दिखाओ, reply in English")
        self.assertEqual(p["language"], "en")
        self.assertEqual(p["language_override"], "en")

    def test_emoji_only_keeps_the_override(self):
        p = run({"language_override": "en"}, "hi", "🙏🙏")
        self.assertEqual(p["language"], "en")


class R2WholeMessageLowSignal(unittest.TestCase):
    def test_r2_ok_prefixed_prose_is_not_low_signal(self):
        self.assertFalse(_is_low_language_signal("ok, what is your return policy for rings bought online?"))
        p = run({"language": "hi"}, "en", "ok, what is your return policy for rings bought online?")
        self.assertEqual(p["language"], "en")

    def test_control_r3_without_ok(self):
        p = run({"language": "hi"}, "en", "what is your return policy for rings bought online?")
        self.assertEqual(p["language"], "en")

    def test_pure_acks_are_still_low_signal(self):
        for t in ("ok", "Ok.", "okk", "yes", "yes please", "ok thanks", "Thank you!", "thank you ji",
                  "sure 👍", "no", "yeah fine", "done", "50000", "😍", "?", "hi", "Hello!"):
            self.assertTrue(_is_low_language_signal(t), t)

    def test_ack_then_request_is_prose(self):
        for t in ("yes please show me more rings", "thanks, do you have earrings", "no I want gold",
                  "sure, what about necklaces"):
            self.assertFalse(_is_low_language_signal(t), t)

    def test_ack_keeps_a_native_script_session(self):
        # The reason acks are low-signal: a Hindi (Devanagari) session is not
        # demoted to English by "ok thanks".
        p = run({"language": "hi"}, "en", "ok thanks")
        self.assertEqual(p["language"], "hi")

    def test_hinglish_after_ok_is_hinglish(self):
        p = run({"language": "en"}, "hi-Latn", "ok, mujhe gold ki ring chahiye 20000 tak")
        self.assertEqual(p["language"], "hi-Latn")

    def test_mixed_script_ack_is_not_low_signal(self):
        # Any non-Latin script proves a script, however short.
        self.assertFalse(_is_low_language_signal("ok ठीक है"))


if __name__ == "__main__":
    unittest.main()
