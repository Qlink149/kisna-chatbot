"""KB v2.1 -- client answers of 2026-09-26: the assembled prompt's content,
campaign expiry, the time-aware welcome, the drop-off message and
GeneralAgent temperature gating."""

import asyncio
import os
import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.ai.config import supports_temperature  # noqa: E402
from kisna_chatbot.prompts.general_agent_kisna import (  # noqa: E402
    build_general_agent_prompt,
    build_locked_values,
)
from kisna_chatbot.prompts.kisna_knowledge_base import (  # noqa: E402
    KISNA_CAMPAIGN_ITEMS,
    build_campaigns_block,
    build_dropoff_message,
)
from kisna_chatbot.processors.service_list import (  # noqa: E402
    build_greeting_text,
    kisna_greeting_line,
)
from kisna_chatbot.utils import reply_composer  # noqa: E402

_IST = ZoneInfo("Asia/Kolkata")
_PROMPT = build_general_agent_prompt(date(2026, 9, 26))

_MORNING = "Good Morning! ☀️ Hope you’re doing well!"
_AFTERNOON = "Good Afternoon! 🌤️ Hope you’re having a good day!"
_EVENING = "Good Evening! 🌆 Hope you’re having a lovely evening!"


class AssembledPromptContentTests(unittest.TestCase):
    """7.3 / 7.4 on the FINAL assembled prompt string."""

    def test_discreet_only_appears_inside_never_rules(self):
        # The word may only appear where the prompt forbids it (the packaging
        # rule and the anti-hallucination example) -- never as a description.
        lines = [line for line in _PROMPT.splitlines() if "discreet" in line.lower()]
        self.assertTrue(lines)
        for line in lines:
            with self.subTest(line=line[:60]):
                self.assertRegex(line.lower(), r"never")

    def test_stale_or_forbidden_strings_have_zero_hits(self):
        for s in (
            "ecom@kisna.com", "₹100 return", "next-day", "next day",
            "Express delivery is used", "My Orders", "richer colour",
            "6th Aug", "5th Nov", "35%", "20%", "TODO-CLIENT", "sells only gold",
            "web search",
        ):
            with self.subTest(s=s):
                self.assertEqual(_PROMPT.count(s), 0, s)

    def test_client_facts_are_present(self):
        self.assertTrue("4–5 working days" in _PROMPT or "4-5 working days" in _PROMPT)
        for s in (
            "My Account", "exclusively in natural", "VVS-FG", "SI-HI", "22KT",
            "purity and weight", "chain snatching",
            "# KIA RESPONSE VOICE (match this style in every customer-facing reply)",
        ):
            with self.subTest(s=s):
                self.assertIn(s, _PROMPT)

    def test_locked_values_is_the_final_section(self):
        self.assertTrue(_PROMPT.rstrip().endswith(build_locked_values().rstrip()))
        self.assertIn("- Diamond grades: VVS-FG, SI-HI", _PROMPT[-1500:])

    def test_support_contact_appears_once(self):
        self.assertEqual(_PROMPT.count("81694 40000"), 1)
        self.assertEqual(_PROMPT.count("10:00am–6:30pm"), 1)

    def test_digital_gold_cancel_rule_survives(self):
        self.assertIn("a digital gold order cannot be cancelled once placed", _PROMPT)

    def test_kia_only_persona(self):
        self.assertIn("Never introduce yourself or sign off under any other name.", _PROMPT)

    def test_model_never_sees_making_charge_percentages(self):
        mc = next(i for i in KISNA_CAMPAIGN_ITEMS if i.id == "making_charges")
        self.assertIsNone(mc.prompt_text)
        self.assertNotIn("35%", build_campaigns_block(date(2026, 9, 26)))


class CampaignExpiryTests(unittest.TestCase):
    def test_campaigns_block_by_date(self):
        nov5 = build_campaigns_block(date(2026, 11, 5))
        self.assertIn("Gold Rate Protection", nov5)
        self.assertIn("Lucky Draw", nov5)
        nov30 = build_campaigns_block(date(2026, 11, 30))
        self.assertNotIn("Gold Rate Protection", nov30)
        self.assertIn("Lucky Draw", nov30)
        dec1 = build_campaigns_block(date(2026, 12, 1))
        self.assertNotIn("Lucky Draw", dec1)
        # Only the explicit "GRP is not running" line is left.
        self.assertEqual(dec1.count("\n- "), 1)
        self.assertIn(self.GRP_OVER, dec1)

    # kisna.com GRP page: "You can lock your gold rate from 6th August to 5th
    # November 2026. Bookings made during this period can be redeemed between
    # 7th August and 10th November 2026."
    GRP_OPEN = "- Gold Rate Protection (GRP) is open for booking now."
    GRP_CLOSED = "- GRP booking has closed for this season."
    GRP_OVER = "- GRP is not running now. Booking AND redemption for this season have both ended"

    def test_grp_booking_phase_until_5_nov(self):
        for day in (date(2026, 9, 30), date(2026, 11, 5)):
            with self.subTest(day=day):
                block = build_campaigns_block(day)
                self.assertIn(self.GRP_OPEN, block)
                self.assertNotIn(self.GRP_CLOSED, block)
                self.assertNotIn("is running now", block)

    def test_grp_redemption_phase_6_to_10_nov(self):
        for day in (date(2026, 11, 6), date(2026, 11, 10)):
            with self.subTest(day=day):
                block = build_campaigns_block(day)
                self.assertIn(self.GRP_CLOSED, block)
                self.assertIn("redeem against their locked rate", block)
                self.assertIn("Do not offer or accept new GRP bookings.", block)
                self.assertNotIn(self.GRP_OPEN, block)

    def test_grp_over_from_11_nov_said_explicitly(self):
        # Without an explicit line the model answered "yes, you can book /
        # still buy" on 11 Nov (KB eval), so the end of the season is stated.
        for day in (date(2026, 11, 11), date(2027, 1, 15)):
            with self.subTest(day=day):
                block = build_campaigns_block(day)
                self.assertIn(self.GRP_OVER, block)
                self.assertIn("can no longer buy or redeem", block)
                self.assertNotIn(self.GRP_OPEN, block)
                self.assertNotIn(self.GRP_CLOSED, block)
        for day in (date(2026, 11, 5), date(2026, 11, 10)):
            self.assertNotIn(self.GRP_OVER, build_campaigns_block(day))

    def test_grp_phases_quote_no_dates(self):
        import re

        for item in KISNA_CAMPAIGN_ITEMS:
            if item.id.startswith("grp_"):
                with self.subTest(item=item.id):
                    self.assertNotRegex(item.prompt_text, r"(?i)\b\d{1,2}(st|nd|rd|th)?\s*(aug|nov)|\bnovember|\baugust")
                    self.assertIsNone(re.search(r"\b20\d\d\b", item.prompt_text))

    def test_rules_reading_live_campaigns_follow_both_phases(self):
        self.assertIn("only while LIVE CAMPAIGNS says GRP is open for booking", _PROMPT)
        self.assertIn("no new GRP advance is accepted", _PROMPT)
        self.assertIn("If it says GRP booking has closed, new bookings and advances are not accepted", _PROMPT)
        self.assertNotIn("only while GRP is running (listed under LIVE CAMPAIGNS)", _PROMPT)

    def test_dropoff_grp_block_still_ends_5_nov(self):
        self.assertIn("Gold Rate Protection (GRP)", build_dropoff_message(date(2026, 11, 5)))
        self.assertNotIn("Gold Rate Protection", build_dropoff_message(date(2026, 11, 6)))

    # The client's drop-off message, pasted as sent (curly apostrophes, en and
    # em dashes, emoji with variation selectors).
    CLIENT_DROPOFF = """\
✨ Exclusive Benefits, Just for You!

Shop beautiful jewellery at KISNA and enjoy:

💎 Diamond Jewellery: Up to 35% OFF on Making Charges
✨ Gold Jewellery: Up to 20% OFF on Making Charges
🛡️ Free 1-Year Jewellery Insurance with every purchase

Discounts apply only to making charges. T&Cs apply.

💰 Gold Rate Protection (GRP): Lock today’s gold rate with just 25% advance and purchase jewellery worth up to 4X your advance. Available on eligible Gold, Diamond, Platinum & Solitaire Jewellery.

https://www.kisna.com/pages/gold-rate-protection

🎉 Lucky Draw: Win 2 Scooters + 1 Car!
📅 Offer: 21 Aug – 30 Nov 2026 | Indian citizens 18+ (excluding Tamil Nadu). T&Cs apply.

https://www.kisna.com/pages/jewellery-offers

💬 Need help? Just reach out to us—we’re always happy to assist!"""
    GRP_BLOCK = (
        "💰 Gold Rate Protection (GRP): Lock today’s gold rate with just 25% advance and purchase "
        "jewellery worth up to 4X your advance. Available on eligible Gold, Diamond, Platinum & "
        "Solitaire Jewellery.\n\nhttps://www.kisna.com/pages/gold-rate-protection\n\n"
    )
    LUCKY_BLOCK = (
        "🎉 Lucky Draw: Win 2 Scooters + 1 Car!\n📅 Offer: 21 Aug – 30 Nov 2026 | Indian citizens "
        "18+ (excluding Tamil Nadu). T&Cs apply.\n\nhttps://www.kisna.com/pages/jewellery-offers\n\n"
    )

    def test_dropoff_is_the_clients_message_character_for_character(self):
        for day in (date(2026, 9, 30), date(2026, 11, 5)):
            with self.subTest(day=day):
                self.assertEqual(build_dropoff_message(day), self.CLIENT_DROPOFF)
        # The typographic characters survive (an editor must not straighten them).
        for ch in ("’", "–", "—", "\U0001F6E1️"):
            self.assertIn(ch, build_dropoff_message(date(2026, 9, 30)))

    def test_dropoff_blocks_expire_by_date(self):
        without_grp = self.CLIENT_DROPOFF.replace(self.GRP_BLOCK, "")
        without_both = without_grp.replace(self.LUCKY_BLOCK, "")
        self.assertNotEqual(without_grp, self.CLIENT_DROPOFF)
        self.assertNotEqual(without_both, without_grp)
        self.assertEqual(build_dropoff_message(date(2026, 11, 6)), without_grp)   # GRP until 5 Nov
        self.assertEqual(build_dropoff_message(date(2026, 11, 30)), without_grp)  # Lucky Draw until 30 Nov
        # Header, the permanent benefits block and footer always.
        self.assertEqual(
            build_dropoff_message(date(2026, 12, 1)),
            "✨ Exclusive Benefits, Just for You!\n\n"
            "Shop beautiful jewellery at KISNA and enjoy:\n\n"
            "💎 Diamond Jewellery: Up to 35% OFF on Making Charges\n"
            "✨ Gold Jewellery: Up to 20% OFF on Making Charges\n"
            "🛡️ Free 1-Year Jewellery Insurance with every purchase\n\n"
            "Discounts apply only to making charges. T&Cs apply.\n\n"
            "💬 Need help? Just reach out to us—we’re always happy to assist!",
        )
        self.assertEqual(build_dropoff_message(date(2026, 12, 1)), without_both)


class GreetingLineTests(unittest.TestCase):
    def _at(self, h, m):
        return kisna_greeting_line(datetime(2026, 9, 27, h, m, tzinfo=_IST))

    def test_ist_bands(self):
        self.assertEqual(self._at(4, 59), "")
        self.assertEqual(self._at(5, 0), _MORNING)
        self.assertEqual(self._at(11, 59), _MORNING)
        self.assertEqual(self._at(12, 0), _AFTERNOON)
        self.assertEqual(self._at(16, 59), _AFTERNOON)
        self.assertEqual(self._at(17, 0), _EVENING)
        self.assertEqual(self._at(20, 59), _EVENING)
        self.assertEqual(self._at(21, 0), "")

    def test_utc_aware_input_is_converted_to_ist(self):
        # 03:45 UTC == 09:15 IST -> morning, not the 03:45 night band.
        utc = datetime(2026, 9, 27, 3, 45, tzinfo=timezone.utc)
        self.assertEqual(kisna_greeting_line(utc), _MORNING)

    def test_new_user_at_night_has_no_leading_blank_line(self):
        text = build_greeting_text(chat_history=[], now=datetime(2026, 9, 27, 23, 0, tzinfo=_IST))
        self.assertTrue(text.startswith("Namaste and welcome to Kisna Diamond & Gold."))

    def test_new_user_by_day_leads_with_time_line(self):
        text = build_greeting_text(chat_history=[], now=datetime(2026, 9, 27, 13, 0, tzinfo=_IST))
        self.assertTrue(text.startswith(_AFTERNOON + "\n\nNamaste and welcome"))

    def test_returning_user_keeps_welcome_back(self):
        text = build_greeting_text(
            chat_history=[{"role": "user", "content": "hi"}],
            user_profile={"username": "Asha"},
            now=datetime(2026, 9, 27, 18, 0, tzinfo=_IST),
        )
        # One message, no stacked time line: first name, then the closer.
        self.assertEqual(
            text,
            "Good Evening, Asha! 👋 Welcome back to Kisna Diamond & Gold. 💎\n\n"
            "How may I assist you today? 😊",
        )


class NoNarrateForClientCopyTests(unittest.TestCase):
    def test_english_greeting_is_not_rewritten(self):
        self.assertNotIn("greeting_new", reply_composer._PERSONALITY_TAGS)
        self.assertNotIn("greeting_return", reply_composer._PERSONALITY_TAGS)

        async def _run():
            data = {
                "messages": {"type": "text", "text": {"body": "hi"}},
                "user_profile": {"language": "en"},
                "bot_response": [{"type": "text", "text": "Hello verbatim", "_compose": "greeting_new"}],
            }
            with patch.object(reply_composer, "narrate", new_callable=AsyncMock) as narr:
                await reply_composer.localize_bot_responses(data)
            narr.assert_not_awaited()
            self.assertEqual(data["bot_response"][0]["text"], "Hello verbatim")

        asyncio.run(_run())

    def test_english_dropoff_never_passes_through_narrate(self):
        from kisna_chatbot.processors import reengagement as re_mod

        async def _run():
            with patch.object(reply_composer, "narrate", new_callable=AsyncMock) as narr, patch.object(
                re_mod, "compose", new_callable=AsyncMock
            ) as comp:
                text, _ = await re_mod.compose_reengagement({"language": "en"})
            narr.assert_not_awaited()
            comp.assert_not_awaited()
            self.assertEqual(text, build_dropoff_message())

        asyncio.run(_run())


class TemperatureTests(unittest.TestCase):
    def test_model_support(self):
        self.assertTrue(supports_temperature("gpt-4o-mini"))
        self.assertFalse(supports_temperature("gpt-5.6-luna"))

    def _call_kwargs(self, model_for_language):
        from kisna_chatbot.ai import openai_responses as oar

        message = MagicMock(type="message")
        message.content = [MagicMock(text='{"message": "ok"}')]
        response = MagicMock(output=[message], usage=None)
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response)
        with patch.object(oar, "get_openai_client", return_value=client), patch.object(
            oar, "resolve_compose_model", return_value=model_for_language
        ), patch.object(oar, "record_usage"):
            asyncio.run(
                oar.run_openai_general_agent(
                    phone_number="919812345678", client_id="kisna", username="A",
                    user_query="hi", chat_history_str="", language="ta",
                )
            )
        return client.responses.create.await_args.kwargs

    def test_temperature_sent_for_gpt_4o_mini(self):
        kwargs = self._call_kwargs("gpt-4o-mini")
        self.assertEqual(kwargs["temperature"], 0.2)

    def test_temperature_omitted_for_gpt_5_6_luna(self):
        kwargs = self._call_kwargs("gpt-5.6-luna")
        self.assertNotIn("temperature", kwargs)


class NoV1ImportTests(unittest.TestCase):
    def test_v1_kb_not_imported_in_app_code(self):
        root = Path(__file__).resolve().parents[1] / "kisna_chatbot"
        pattern = re.compile(r"\bKISNA_KNOWLEDGE_BASE\b")
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "kisna_knowledge_base.py":
                continue  # the (unused) definition itself
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
