"""Flow sends: Gupshup's v3 "accepted" reply counts as confirmed, and no
path sends the same Flow twice (no retry loop in the Flow senders; on a
failure the turn falls back to the locator-link text, never the form again)."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.processors import response_manager as rm  # noqa: E402

V3_ACCEPTED = {
    "messages": [{"id": "6ef434fe-7d97-4460-a7ca-271d9e76de6d"}],
    "messaging_product": "whatsapp",
    "contacts": [{"input": "919116914178", "wa_id": "919116914178"}],
}


class SendAcceptedTests(unittest.TestCase):
    def test_both_reply_shapes_count_as_accepted(self):
        self.assertTrue(rm._send_accepted({"status": "submitted", "messageId": "x"}))
        self.assertTrue(rm._send_accepted(V3_ACCEPTED))

    def test_real_non_acceptance_still_warns(self):
        for bad in ({"status": "error"}, {"messages": []}, {"messages": [{}]}, {"contacts": []}, {}):
            self.assertFalse(rm._send_accepted(bad), bad)

    def _run(self, items, sender_result):
        mgr = rm.ResponseManager() if hasattr(rm, "ResponseManager") else None
        self.assertIsNotNone(mgr)
        handler = MagicMock(return_value=sender_result)
        mgr._handlers = {"flow": handler, "text": MagicMock(return_value={"status": "submitted"})}
        with patch.object(rm, "is_window_open", return_value=True), patch.object(
            rm.outbound_rate_limiter, "wait_if_needed", return_value=False
        ), patch.object(rm.time, "sleep") as sleep, patch.object(rm, "logger") as log:
            mgr.handle_responses({"phone_number": "919116914178", "bot_response": items, "user_profile": {}})
        return handler, sleep, log

    def test_v3_accept_no_warning_and_pacing_applied(self):
        handler, sleep, log = self._run([{"type": "flow", "flow": "store_visit"}, {"type": "text", "text": "x"}], V3_ACCEPTED)
        handler.assert_called_once()
        warned = [c.args[0] for c in log.warning.call_args_list]
        self.assertFalse(any("not confirmed" in str(w) for w in warned), warned)
        self.assertTrue(sleep.called)  # post-send pacing restored


class FlowSentOnceTests(unittest.TestCase):
    def test_store_visit_sender_posts_once_and_does_not_retry(self):
        from kisna_chatbot.whatsapp_functions.flow import send_store_visit_flow as sender

        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": "123"}), patch.object(
            sender, "store_visit_form_available", return_value=True
        ), patch.object(sender, "remember_send"), patch.object(
            sender.httpx, "post", side_effect=sender.httpx.ReadTimeout("slow")
        ) as post:
            with self.assertRaises(sender.httpx.ReadTimeout):
                sender.send_store_visit_flow("919116914178", "Body", first_name="R")
        self.assertEqual(post.call_count, 1)

    def test_failed_flow_send_falls_back_to_link_not_the_form_again(self):
        mgr = rm.ResponseManager()
        with patch(
            "kisna_chatbot.whatsapp_functions.flow.send_store_visit_flow.send_store_visit_flow",
            side_effect=RuntimeError("Gupshup 500"),
        ) as send_flow, patch.object(rm, "send_text_message_with_retry", return_value={"status": "submitted"}) as text:
            mgr._handle_flow("919116914178", {"type": "flow", "flow": "store_visit", "text": "Body", "name": "R"})
        self.assertEqual(send_flow.call_count, 1)
        text.assert_called_once()
        self.assertIn("kisna.com/store", text.call_args.kwargs["bot_response"]["text"])


if __name__ == "__main__":
    unittest.main()
