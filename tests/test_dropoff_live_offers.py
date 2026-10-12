"""Drop-off message: the making-charge percentages come from the Clara
promotions API (the same figures as "View Offers"); the last successful result
is used when the API fails; nothing else in the message changes."""

import asyncio
import os
import time
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.processors import reengagement as re  # noqa: E402
from kisna_chatbot.prompts.kisna_knowledge_base import build_dropoff_message  # noqa: E402

DAY = date(2026, 10, 12)  # GRP and Lucky Draw both live

# The two rows the API returned on 2026-10-12 (trimmed).
API_ROWS = [
    {"category": "Diamond", "discountLable": "UP TO 100% OFF* ON MAKING CHARGES OF DIAMOND JEWELLERY",
     "discount": 100, "isFlat": False, "discOn": "Labour", "fromAmt": 1000001, "toAmt": 9999999,
     "active": True, "status": "active"},
    {"category": "Gold", "discountLable": "UP TO 100% OFF* ON MAKING CHARGES OF GOLD JEWELLERY",
     "discount": 100, "isFlat": False, "discOn": "Labour", "fromAmt": 2000001, "toAmt": 9999999,
     "active": True, "status": "active"},
]
GET_PROMOTIONS = "kisna_chatbot.integrations.clara_api.get_promotions"


class FiguresFromApiTests(unittest.TestCase):
    def test_todays_api_rows(self):
        self.assertEqual(re.making_charges_from_promotions(API_ROWS), {"diamond": 100, "gold": 100})

    def test_highest_active_percentage_per_category(self):
        rows = [
            {"category": "Diamond", "discount": 25, "discOn": "Labour", "active": True},
            {"category": "Diamond", "discount": 40, "discOn": "Labour", "active": True},
            {"category": "Diamond", "discount": 90, "discOn": "Labour", "active": False},  # inactive
            {"category": "Gold", "discount": 5000, "discOn": "Labour", "isFlat": True, "active": True},  # flat ₹
            {"category": "Gold", "discount": 15, "discOn": "Metal", "active": True},  # not making charges
            {"category": "Platinum", "discount": 50, "discOn": "Labour", "active": True},  # not in the message
        ]
        self.assertEqual(re.making_charges_from_promotions(rows), {"diamond": 40})
        self.assertEqual(re.making_charges_from_promotions([]), {})


class MessageTests(unittest.TestCase):
    def test_live_figures_replace_only_the_two_percentages(self):
        live = build_dropoff_message(DAY, {"diamond": 100, "gold": 100})
        static = build_dropoff_message(DAY)
        self.assertEqual(
            live,
            static.replace("Diamond Jewellery: Up to 35%", "Diamond Jewellery: Up to 100%")
                  .replace("Gold Jewellery: Up to 20%", "Gold Jewellery: Up to 100%"),
        )
        self.assertIn("💎 Diamond Jewellery: Up to 100% OFF on Making Charges", live)
        self.assertIn("✨ Gold Jewellery: Up to 100% OFF on Making Charges", live)
        for kept in ("Free 1-Year Jewellery Insurance", "Discounts apply only to making charges. T&Cs apply.",
                     "Gold Rate Protection (GRP)", "Lucky Draw", "Exclusive Benefits, Just for You!"):
            self.assertIn(kept, live)

    def test_category_without_an_offer_loses_its_line(self):
        live = build_dropoff_message(DAY, {"diamond": 30})
        self.assertIn("Diamond Jewellery: Up to 30%", live)
        self.assertNotIn("Gold Jewellery: Up to", live)
        self.assertIn("Discounts apply only to making charges", live)

    def test_no_offers_keeps_insurance_only(self):
        live = build_dropoff_message(DAY, {})
        self.assertNotIn("% OFF on Making Charges", live)
        self.assertNotIn("Discounts apply only to making charges", live)
        self.assertIn("Free 1-Year Jewellery Insurance", live)
        self.assertIn("Gold Rate Protection (GRP)", live)

    def test_default_is_the_clients_static_text(self):
        self.assertIn("Up to 35%", build_dropoff_message(DAY))


@pytest.mark.dropoff_live_offers
class LastSuccessfulResultTests(unittest.TestCase):
    def setUp(self):
        re._live_offers.update(pct=None, fetched_at=0.0, failed_at=0.0)
        self.now = 1_000_000.0
        p = patch.object(re.time, "time", side_effect=lambda: self.now)
        p.start()
        self.addCleanup(p.stop)

    def fetch(self):
        return asyncio.run(re.live_making_charges())

    def test_success_is_cached_for_two_hours(self):
        api = AsyncMock(return_value=API_ROWS)
        with patch(GET_PROMOTIONS, api):
            self.assertEqual(self.fetch(), {"diamond": 100, "gold": 100})
            self.now += 2 * 3600 - 1
            self.fetch()
            self.assertEqual(api.await_count, 1)
            self.now += 2
            self.fetch()
            self.assertEqual(api.await_count, 2)

    def test_failure_uses_the_last_successful_result(self):
        with patch(GET_PROMOTIONS, AsyncMock(return_value=API_ROWS)):
            self.fetch()
        self.now += 3 * 3600
        with patch(GET_PROMOTIONS, AsyncMock(side_effect=RuntimeError("Clara 503"))):
            self.assertEqual(self.fetch(), {"diamond": 100, "gold": 100})

    def test_failure_before_any_success_sends_no_percentages(self):
        with patch(GET_PROMOTIONS, AsyncMock(side_effect=RuntimeError("Clara 503"))):
            self.assertEqual(self.fetch(), {})

    def test_failure_is_retried_after_five_minutes_not_every_send(self):
        api = AsyncMock(side_effect=RuntimeError("Clara 503"))
        with patch(GET_PROMOTIONS, api):
            self.fetch()
            self.now += 60
            self.fetch()
            self.assertEqual(api.await_count, 1)
            self.now += 300
            self.fetch()
            self.assertEqual(api.await_count, 2)

    def test_empty_api_result_is_a_success_not_a_failure(self):
        with patch(GET_PROMOTIONS, AsyncMock(return_value=API_ROWS)):
            self.fetch()
        self.now += 3 * 3600
        with patch(GET_PROMOTIONS, AsyncMock(return_value=[])):
            self.assertEqual(self.fetch(), {})


@pytest.mark.dropoff_live_offers
class SentMessageTests(unittest.TestCase):
    def setUp(self):
        re._live_offers.update(pct=None, fetched_at=0.0, failed_at=0.0)
        env = patch.dict(os.environ, {"KISNA_REENGAGE_ENABLED": "true"})
        env.start()
        self.addCleanup(env.stop)

    def _sweep(self, language="en"):
        profile = {"phone_number": "919812345678", "client_id": "kisna", "language": language,
                   "last_message_at": int(time.time()) - 4 * 3600, "last_inbound_at": int(time.time()) - 4 * 3600}
        find = MagicMock()
        find.sort.return_value.limit.return_value = [profile]
        with patch(GET_PROMOTIONS, AsyncMock(return_value=API_ROWS)), patch.object(
            re.users, "find", return_value=find
        ), patch.object(re.users, "update_one"), patch.object(
            re, "get_takeover_status", return_value=None
        ), patch.object(
            re, "compose", new_callable=AsyncMock, side_effect=lambda key, text, **k: text
        ) as comp, patch.object(re, "send_text_message_with_retry") as send, patch.object(re, "save_agent_message"):
            asyncio.run(re.sweep_reengagement())
        return send, comp

    def test_sent_message_carries_the_live_figures(self):
        send, _ = self._sweep()
        text = send.call_args[0][1]["text"]
        self.assertIn("Diamond Jewellery: Up to 100% OFF on Making Charges", text)
        self.assertIn("Gold Jewellery: Up to 100% OFF on Making Charges", text)
        self.assertNotIn("35%", text)

    def test_translation_pins_the_live_figures(self):
        _, comp = self._sweep(language="hi-Latn")
        pins = comp.await_args.kwargs["pin"]
        self.assertIn("100%", pins)
        self.assertIn("25%", pins)  # GRP advance
        self.assertNotIn("35%", pins)


if __name__ == "__main__":
    unittest.main()
