"""WhatsApp's 1,024-character cap on a Flow message body, checked on the text
actually sent -- i.e. AFTER translation. Over the cap, the client's English
copy goes instead (a rejected send would mean no form at all)."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.prompts import form_copy  # noqa: E402
from kisna_chatbot.prompts.form_copy import FLOW_BODY_MAX_CHARS, fit_flow_body  # noqa: E402


class FitFlowBodyTests(unittest.TestCase):
    def test_every_english_copy_fits(self):
        for name in ("COMPLAINT_PREFORM", "CALLBACK_PREFORM", "VIDEO_CALL_PREFORM", "HANDOFF_FALLBACK"):
            self.assertLessEqual(len(getattr(form_copy, name)), FLOW_BODY_MAX_CHARS, name)

    def test_translation_within_limit_is_kept(self):
        hindi = "✨ हमें आपकी सहायता करने में खुशी होगी! " * 10
        self.assertEqual(fit_flow_body(hindi, form_copy.CALLBACK_PREFORM), hindi.strip())

    def test_exactly_at_the_limit_is_kept(self):
        text = "क" * FLOW_BODY_MAX_CHARS
        self.assertEqual(fit_flow_body(text, "EN"), text)

    def test_over_the_limit_falls_back_to_english(self):
        too_long = "க" * (FLOW_BODY_MAX_CHARS + 1)
        self.assertEqual(fit_flow_body(too_long, form_copy.HANDOFF_FALLBACK), form_copy.HANDOFF_FALLBACK)

    def test_empty_uses_english(self):
        self.assertEqual(fit_flow_body(None, "EN"), "EN")
        self.assertEqual(fit_flow_body("  ", "EN"), "EN")


class SenderTests(unittest.TestCase):
    """Each sender applies the check to the body it posts."""

    def setUp(self):
        # Callback / video senders compute slots; no Mongo in unit tests.
        from kisna_chatbot.utils.support_slots import set_capacity_overrides

        set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)

    def tearDown(self):
        from kisna_chatbot.utils.support_slots import clear_capacity_overrides

        clear_capacity_overrides()

    def _sent_body(self, module, func, env, body_text):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"ok": True}
        with patch.dict(os.environ, env), patch.object(module.httpx, "post", return_value=resp) as post:
            func("919812345678", body_text)
        return post.call_args.kwargs["json"]["interactive"]["body"]["text"]

    def test_callback_video_and_complaint_senders(self):
        from kisna_chatbot.whatsapp_functions.flow import (
            send_callback_request_flow as cb,
            send_damage_complaint as dc,
            send_video_call_request_flow as vc,
        )

        cases = (
            (cb, cb.send_callback_request_flow, {"KISNA_CALLBACK_FLOW_ID": "1"}, form_copy.CALLBACK_PREFORM),
            (vc, vc.send_video_call_request_flow, {"KISNA_VIDEOCALL_FLOW_ID": "2"}, form_copy.VIDEO_CALL_PREFORM),
            (dc, dc.send_damage_complaint_flow, {}, form_copy.COMPLAINT_PREFORM),
        )
        for module, func, env, english in cases:
            self.assertEqual(self._sent_body(module, func, env, "छोटा"), "छोटा", module.__name__)
            self.assertEqual(
                self._sent_body(module, func, env, "x" * (FLOW_BODY_MAX_CHARS + 50)), english, module.__name__
            )


if __name__ == "__main__":
    unittest.main()
