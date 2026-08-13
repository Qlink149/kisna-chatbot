"""Asking FOR the customer-care number is not asking to be put through.

"What's the customer care number?" used to match _HUMAN_HANDOFF_RE and go
straight to a live agent: the question went unanswered and a human was paged
who was never needed. Now the bot answers with the details and offers the
transfer as a choice.
"""

import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_TOKEN": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "JWT_SECRET_KEY": "test",
    "SYSTEM_API_KEY": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_OFFERS_API": "http://localhost/offers",
    "KISNA_STORE_API": "http://localhost/stores",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "KB_ENABLED": "false",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    _is_support_contact_request,
)
from kisna_chatbot.processors.service_list import (  # noqa: E402
    _handle_support_connect_reply,
)
from kisna_chatbot.processors.support_handler import (  # noqa: E402
    SUPPORT_CONTACT_MSGID,
    build_support_contact_response,
)


class SupportContactDetectionTests(unittest.TestCase):
    WANTS_DETAILS = [
        "customer care number",
        "what is the customer care number?",
        "support number please",
        "customer care ka number",
        "helpline",
        "support team contact details",
        "customer care email id",
        "how do i contact kisna",
        "give me the support phone no",
    ]
    WANTS_TRANSFER = [
        "connect me with an agent",
        "talk to a human",
        "customer care se baat karni hai",
        "please connect me to customer care",
        "I want to talk to a representative from Kisna",
        "transfer me to support",
    ]

    def test_contact_requests_detected(self):
        for text in self.WANTS_DETAILS:
            with self.subTest(text=text):
                self.assertTrue(_is_support_contact_request(text))

    def test_transfer_requests_are_not_contact_requests(self):
        """A message that asks to be CONNECTED still goes to a live agent."""
        for text in self.WANTS_TRANSFER:
            with self.subTest(text=text):
                self.assertFalse(_is_support_contact_request(text))


class SupportContactResponseTests(unittest.TestCase):
    def test_response_carries_details_and_an_offer(self):
        profile: dict = {}
        responses = build_support_contact_response(profile)
        self.assertEqual(len(responses), 1)
        item = responses[0]
        self.assertEqual(item["type"], "quickreply")
        self.assertEqual(item["msgid"], SUPPORT_CONTACT_MSGID)
        text = item["text"]
        self.assertIn("Phone:", text)
        self.assertIn("Email:", text)
        self.assertIn("Hours:", text)
        titles = [o["title"] for o in item["options"]]
        self.assertIn("Yes, connect me", titles)
        self.assertIn("No, thanks", titles)
        self.assertTrue(profile["awaiting_support_connect"])

    def test_yes_connects_to_an_agent(self):
        profile = {"username": "Test"}
        data = {"phone_number": "919999999999", "user_profile": profile}
        with patch(
            "kisna_chatbot.processors.support_handler.send_customer_support_template"
        ), patch(
            "kisna_chatbot.processors.support_handler.get_support_status",
            return_value={"status": "open"},
        ):
            _handle_support_connect_reply(
                "Yes, connect me", data, profile, "919999999999"
            )
        self.assertEqual(data["classified_category"], "human_handoff")
        self.assertTrue(profile.get("live_agent_required"))
        self.assertNotIn("awaiting_support_connect", profile)

    def test_no_closes_politely_without_paging_a_human(self):
        profile = {"username": "Test", "awaiting_support_connect": True}
        data = {"phone_number": "919999999999", "user_profile": profile}
        _handle_support_connect_reply("No, thanks", data, profile, "919999999999")
        self.assertEqual(data["classified_category"], "general")
        self.assertFalse(profile.get("live_agent_required"))
        self.assertNotIn("awaiting_support_connect", profile)


class SupportContactRoutingTests(unittest.TestCase):
    def _data(self, body: str, **profile_extra) -> dict:
        return {
            "phone_number": "919999999999",
            "messages": {"text": {"body": body}},
            "user_profile": {
                "chat_history": [],
                "service_selected": "",
                "last_message_at": int(time.time()),
                **profile_extra,
            },
            "client_id": "kisna",
        }

    def test_number_request_answers_instead_of_handing_off(self):
        async def _run():
            clf = Classifier()
            data = self._data("what is the customer care number?")
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent":"human_handoff","confidence":0.95,'
                '"language":"en","entities":{}}',
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "support_contact")
            self.assertFalse(result["user_profile"].get("live_agent_required"))
            self.assertIn("Phone:", result["bot_response"][0]["text"])

        asyncio.run(_run())

    def test_typed_yes_after_the_offer_connects(self):
        async def _run():
            clf = Classifier()
            data = self._data("haan", awaiting_support_connect=True)
            with patch(
                "kisna_chatbot.processors.support_handler."
                "send_customer_support_template"
            ), patch(
                "kisna_chatbot.processors.support_handler.get_support_status",
                return_value={"status": "open"},
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "human_handoff")
            self.assertTrue(result["user_profile"].get("live_agent_required"))

        asyncio.run(_run())

    def test_explicit_transfer_request_still_hands_off(self):
        async def _run():
            clf = Classifier()
            data = self._data("connect me with an agent")
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent":"human_handoff","confidence":0.95,'
                '"language":"en","entities":{}}',
            ), patch(
                "kisna_chatbot.processors.support_handler."
                "send_customer_support_template"
            ), patch(
                "kisna_chatbot.processors.support_handler.get_support_status",
                return_value={"status": "open"},
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "human_handoff")
            self.assertTrue(result["user_profile"].get("live_agent_required"))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
