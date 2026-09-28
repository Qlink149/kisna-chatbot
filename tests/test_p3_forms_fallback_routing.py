"""P3: client form copy, confirmation variants by working hours, the 5-minute
fallback gate, the holiday horizon, refund-status routing, localisation pins,
and the dead-code / workflow guarantees."""

import asyncio
import os
import unittest
from datetime import date, datetime, timedelta
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

from kisna_chatbot.models.enums import FLowId  # noqa: E402
from kisna_chatbot.processors import complaint_agent as ca  # noqa: E402
from kisna_chatbot.processors import callback_agent as cba  # noqa: E402
from kisna_chatbot.processors import handoff_sweep as hs  # noqa: E402
from kisna_chatbot.processors import support_handler as sh  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    _ACTION_INTENT_RE,
    _programmatic_intent_fallback,
    _programmatic_intent_override,
    _route_resolved_intent,
)
from kisna_chatbot.processors.response_manager import ResponseManager  # noqa: E402
from kisna_chatbot.processors.service_list import (  # noqa: E402
    build_callback_flow_bot_response,
    build_complaint_flow_bot_response,
    build_video_call_flow_bot_response,
)
from kisna_chatbot.prompts import form_copy  # noqa: E402
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier_intent  # noqa: E402
from kisna_chatbot.prompts.general_agent_kisna import _WRAPPER  # noqa: E402
from kisna_chatbot.prompts.kisna_knowledge_base import REFUND_PROCESSING_TEXT  # noqa: E402
from kisna_chatbot.utils import reply_composer, support_hours  # noqa: E402
from kisna_chatbot.utils.support_hours import (  # noqa: E402
    SUPPORT_HOLIDAYS,
    is_within_working_hours,
    working_seconds_between,
)

IST = ZoneInfo("Asia/Kolkata")
MON = date(2026, 9, 28)   # Monday, not a holiday
SAT = date(2026, 10, 3)
SUN = date(2026, 10, 4)
HOLIDAY = date(2026, 10, 2)  # Gandhi Jayanti (a Friday)
ID = "KIS-CB-20260928-A1B2"
SLOT = "29 September 2026 · 10:00 AM–1:00 PM"


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


# ------------------------------------------------------------- client copy
class ClientCopyVerbatimTests(unittest.TestCase):
    """The exact strings the code sends, checked against the client's document."""

    def test_pre_form_messages(self):
        self.assertEqual(
            build_complaint_flow_bot_response()["text"],
            "We're here to help! 💙 Please share the details of your concern below, "
            "and our support team will review it and get back to you shortly.",
        )
        expected = (
            "✨ We'd be happy to assist you! Please share your details below, and "
            "our jewellery expert will connect with you at your preferred time. 📞💎"
        )
        self.assertEqual(build_callback_flow_bot_response()["text"], expected)
        self.assertEqual(build_video_call_flow_bot_response()["text"], expected)

    def test_complaint_confirmation_shows_request_id_and_one_working_day(self):
        (item,) = ca._build_confirmation("KIS-CMP-20260928-A1B2")
        self.assertEqual(
            item["text"],
            "Thank you for reaching out to Kisna Diamond & Gold. 💙\n"
            "Your complaint has been successfully registered. 📝\n"
            "Request ID: KIS-CMP-20260928-A1B2\n"
            "Our support team will review your concern and get in touch with you "
            "within 1 working day.\n"
            "We appreciate your patience and thank you for choosing Kisna. ✨",
        )
        self.assertEqual(item["_compose"], "complaint_registered")
        self.assertNotIn("24 hours", item["text"])

    def test_callback_confirmations(self):
        head = (
            "Thank you for reaching out to Kisna Diamond & Gold! 💎\n"
            "{line2}\n"
            f"Request ID: {ID}\n"
            f"Scheduled for: {SLOT}\n"
            "Our jewellery expert will connect with you during your selected time slot. ✨"
        )
        cases = {
            ("callback", True): head.format(
                line2="Your callback request has been successfully registered. 📞"
            ) + "\nWe appreciate your patience and look forward to assisting you.",
            ("callback", False): head.format(
                line2="Our team is currently offline, but your callback request has "
                "been successfully registered. 📞"
            ),
            ("video_call", True): head.format(
                line2="Your video callback request has been successfully registered. 📞"
            ) + "\nWe appreciate your patience and look forward to assisting you!",
            ("video_call", False): head.format(
                line2="Our team is currently offline, but your video callback request "
                "has been successfully registered. 📞"
            ) + "\nThank you for your patience. We look forward to assisting you!",
        }
        for (kind, open_now), expected in cases.items():
            with self.subTest(kind=kind, open_now=open_now):
                now = at(MON, 11) if open_now else at(SUN, 11)
                self.assertEqual(
                    form_copy.callback_confirmation(ID, kind, scheduled_for=SLOT, now=now),
                    expected,
                )

    def test_scheduled_for_uses_the_client_format(self):
        self.assertEqual(form_copy.format_scheduled_for("2026-09-29", "10-13"),
                         "29 September 2026 · 10:00 AM–1:00 PM")
        self.assertEqual(form_copy.format_scheduled_for("2026-10-05", "13-15"),
                         "5 October 2026 · 1:00 PM–3:00 PM")
        self.assertEqual(form_copy.format_scheduled_for("2026-10-03", "10-16"),
                         "3 October 2026 · 10:00 AM–4:00 PM")
        self.assertEqual(form_copy.format_scheduled_for("2026-09-29", "morning"),
                         "29 September 2026 · 10:00 AM–1:00 PM")  # legacy id
        (item,) = cba._build_confirmation(ID, "callback", preferred_date="2026-09-29",
                                          preferred_time="15-18", now=at(MON, 11))
        self.assertIn("Scheduled for: 29 September 2026 · 3:00 PM–6:00 PM\n", item["text"])
        self.assertNotIn("Evening", item["text"])

    def test_handoff_fallback_text(self):
        self.assertEqual(
            form_copy.HANDOFF_FALLBACK,
            "Apologies for the delayed response. 🙏\n"
            "We're currently experiencing a high volume of inquiries, which may result "
            "in a slightly longer response time than usual. Please rest assured that our "
            "team is working diligently to assist you as soon as possible.\n"
            "✨ We'd be delighted to assist you! Please share your details below, and one "
            "of our jewellery experts will connect with you at your preferred time. 📞💎",
        )
        self.assertIs(hs._FALLBACK_TEXT, form_copy.HANDOFF_FALLBACK)

    def test_no_other_complaint_response_time_in_outbound_code(self):
        root = Path(__file__).resolve().parents[1] / "kisna_chatbot"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for n, line in enumerate(text.splitlines(), 1):
                if "24 hours" in line and "complain" in line.lower():
                    self.fail(f"{path}:{n} still describes complaint response time as 24 hours")


# ------------------------------------------------- working hours (Part 6)
class WorkingHoursTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertFalse(is_within_working_hours(at(MON, 9, 59)))
        self.assertTrue(is_within_working_hours(at(MON, 10, 0)))
        self.assertTrue(is_within_working_hours(at(MON, 18, 29)))
        self.assertFalse(is_within_working_hours(at(MON, 18, 30)))
        self.assertTrue(is_within_working_hours(at(SAT, 15, 59)))
        self.assertFalse(is_within_working_hours(at(SAT, 16, 0)))
        for h in (0, 9, 12, 15, 23):
            self.assertFalse(is_within_working_hours(at(SUN, h)))
        self.assertFalse(is_within_working_hours(at(HOLIDAY, 12)))

    def test_confirmation_variant_follows_the_boundaries(self):
        def variant(now):
            text = form_copy.callback_confirmation(ID, "callback", scheduled_for=SLOT, now=now)
            return "offline" if "currently offline" in text else "open"

        self.assertEqual(variant(at(MON, 9, 59)), "offline")
        self.assertEqual(variant(at(MON, 10, 0)), "open")
        self.assertEqual(variant(at(MON, 18, 29)), "open")
        self.assertEqual(variant(at(MON, 18, 30)), "offline")
        self.assertEqual(variant(at(SAT, 15, 59)), "open")
        self.assertEqual(variant(at(SAT, 16, 0)), "offline")
        self.assertEqual(variant(at(SUN, 12)), "offline")
        self.assertEqual(variant(at(HOLIDAY, 12)), "offline")

    def test_support_handler_branches_use_the_single_function(self):
        profile = {"username": "A"}
        with patch.object(sh, "is_within_working_hours", return_value=False), patch.object(
            sh, "_notify_admins"
        ):
            out = sh.build_expert_support_bot_response("919812345678", profile, now=at(MON, 12))
        self.assertIn("currently offline", out[0]["text"])
        with patch.object(sh, "is_within_working_hours", return_value=True), patch.object(
            sh, "_notify_admins"
        ):
            out = sh.build_expert_support_bot_response("919812345678", profile, now=at(SUN, 12))
        self.assertIn("connecting you", out[0]["text"])

    def test_holiday_horizon_at_least_60_days_out(self):
        last = date.fromisoformat(max(SUPPORT_HOLIDAYS))
        self.assertGreater(
            last, date.today() + timedelta(days=60),
            "SUPPORT_HOLIDAYS is about to run out -- extend it (support_hours.py)",
        )
        for key in ("2027-01-26", "2027-03-22", "2027-08-15", "2027-10-02",
                    "2027-10-09", "2027-10-29", "2027-10-30", "2027-12-25", "2026-12-25", "2027-01-01"):
            self.assertIn(key, SUPPORT_HOLIDAYS)
        self.assertIn("PROVISIONAL", Path(support_hours.__file__).read_text(encoding="utf-8"))


# -------------------------------------------------- 5-minute gate (Part 5)
class FallbackGateTests(unittest.TestCase):
    def _epoch(self, dt: datetime) -> int:
        return int(dt.timestamp())

    def kind(self, req: datetime, now: datetime):
        return hs._fallback_kind(self._epoch(req), self._epoch(now), 300)

    def test_request_at_0958_fires_at_1005_not_1003(self):
        self.assertIsNone(self.kind(at(MON, 9, 58), at(MON, 10, 3)))
        self.assertEqual(self.kind(at(MON, 9, 58), at(MON, 10, 5)), hs.FALLBACK)

    def test_five_working_minutes_before_close_is_the_fallback(self):
        self.assertIsNone(self.kind(at(MON, 12, 0), at(MON, 12, 4)))
        self.assertEqual(self.kind(at(MON, 12, 0), at(MON, 12, 5)), hs.FALLBACK)
        self.assertEqual(self.kind(at(MON, 18, 25), at(MON, 18, 30)), hs.FALLBACK)

    def test_request_at_1828_gets_the_at_close_form_at_1830_and_nothing_next_morning(self):
        tue = MON + timedelta(days=1)
        self.assertEqual(working_seconds_between(at(MON, 18, 28), at(MON, 18, 33)), 120)
        self.assertIsNone(self.kind(at(MON, 18, 28), at(MON, 18, 29)))
        self.assertEqual(self.kind(at(MON, 18, 28), at(MON, 18, 30)), hs.AT_CLOSE)
        self.assertIsNone(self.kind(at(MON, 18, 28), at(tue, 10, 3)))
        self.assertIsNone(self.kind(at(MON, 18, 28), at(tue, 18, 30)))

    def test_saturday_close_is_1600(self):
        self.assertEqual(self.kind(at(SAT, 15, 58), at(SAT, 16, 0)), hs.AT_CLOSE)

    def test_never_fires_on_a_later_day_even_when_long_overdue(self):
        tue = MON + timedelta(days=1)
        self.assertIsNone(self.kind(at(MON, 12, 0), at(tue, 12, 0)))

    def test_sunday_and_holiday_accrue_nothing(self):
        self.assertEqual(working_seconds_between(at(SUN, 10), at(SUN, 18)), 0)
        self.assertEqual(working_seconds_between(at(HOLIDAY, 10), at(HOLIDAY, 18)), 0)
        self.assertIsNone(self.kind(at(SUN, 12), at(SUN, 19)))

    def test_candidate_query_is_bounded_to_today_ist(self):
        find = MagicMock()
        find.sort.return_value.limit.return_value = []
        now = at(MON, 18, 30)
        with patch.object(hs.time, "time", return_value=now.timestamp()), patch.object(
            hs.users, "find", return_value=find
        ) as find_mock:
            asyncio.run(hs._sweep_callback_fallback(25))
        bounds = find_mock.call_args[0][0]["live_agent_requested_at"]
        self.assertEqual(bounds["$gte"], self._epoch(at(MON, 0, 0)))
        self.assertEqual(bounds["$lte"], self._epoch(now))

    def _deliver(self, requested: datetime, now: datetime, language="en", compose_result=""):
        profile = {
            "phone_number": "919812345678", "client_id": "kisna", "language": language,
            "live_agent_required": True, "live_agent_requested_at": self._epoch(requested),
        }
        with patch.object(
            hs.users, "find_one_and_update", return_value={"phone_number": "919812345678"}
        ) as armed, patch.object(hs.callback_requests, "find_one", return_value=None), patch.object(
            hs, "compose", new_callable=AsyncMock, return_value=compose_result
        ) as comp, patch.object(hs, "send_text_message_with_retry") as text, patch.object(
            hs, "send_callback_request_flow", return_value={"ok": True}
        ) as form, patch.object(hs, "save_agent_message"):
            fired = asyncio.run(hs._process_one_handoff(profile, self._epoch(now)))
        return fired, armed, comp, text, form

    def test_1828_unanswered_sends_the_after_hours_form_at_1830_as_one_message(self):
        fired, armed, _, text, form = self._deliver(at(MON, 18, 28), at(MON, 18, 30))
        self.assertTrue(fired)
        armed.assert_called_once()
        form.assert_called_once_with("919812345678", form_copy.CALLBACK_PREFORM)
        self.assertNotIn("Apologies", form.call_args[0][1])
        text.assert_not_called()
        # ...and nothing the next morning.
        tue = MON + timedelta(days=1)
        fired, armed, _, text, form = self._deliver(at(MON, 18, 28), at(tue, 10, 3))
        self.assertFalse(fired)
        armed.assert_not_called()
        form.assert_not_called()
        text.assert_not_called()

    def test_fallback_is_one_form_message_with_the_fallback_text_as_body(self):
        fired, _, comp, text, form = self._deliver(at(MON, 12, 0), at(MON, 12, 5))
        self.assertTrue(fired)
        comp.assert_not_awaited()
        form.assert_called_once_with("919812345678", form_copy.HANDOFF_FALLBACK)
        text.assert_not_called()

    def test_fallback_translated_faithfully_and_english_on_failure(self):
        _, _, comp, _, form = self._deliver(at(MON, 12, 0), at(MON, 12, 5), "hi", "अनुवाद")
        self.assertEqual(comp.await_args.kwargs["language"], "hi")
        self.assertEqual(comp.await_args.args[0], "handoff_fallback")
        self.assertEqual(form.call_args[0][1], "अनुवाद")
        _, _, comp, _, form = self._deliver(at(MON, 18, 28), at(MON, 18, 30), "hi", "अनुवाद")
        self.assertEqual(comp.await_args.args[0], "handoff_at_close")
        _, _, _, _, form = self._deliver(at(MON, 12, 0), at(MON, 12, 5), "ta", "")
        self.assertEqual(form.call_args[0][1], form_copy.HANDOFF_FALLBACK)

    def test_no_flow_configured_falls_back_to_plain_text(self):
        profile = {
            "phone_number": "919812345678", "client_id": "kisna", "language": "en",
            "live_agent_required": True, "live_agent_requested_at": self._epoch(at(MON, 12, 0)),
        }
        with patch.object(
            hs.users, "find_one_and_update", return_value={"phone_number": "919812345678"}
        ), patch.object(hs.callback_requests, "find_one", return_value=None), patch.object(
            hs, "send_text_message_with_retry"
        ) as text, patch.object(hs, "send_callback_request_flow", return_value=None), patch.object(
            hs, "save_agent_message"
        ):
            asyncio.run(hs._process_one_handoff(profile, self._epoch(at(MON, 12, 5))))
        self.assertEqual(text.call_args[0][1]["text"], form_copy.HANDOFF_FALLBACK)


# ------------------------------------------------------ routing (Part 7)
class RefundStatusRoutingTests(unittest.TestCase):
    def test_refund_chase_is_overridden_but_a_dispute_is_not(self):
        for t in ("My refund hasn't come", "refund kab milega", "where is my refund",
                  "I haven't received my refund"):
            with self.subTest(t=t):
                self.assertEqual(_programmatic_intent_override(t), ("refund_status", 0.95))
                self.assertEqual(_programmatic_intent_fallback(t), ("refund_status", 0.95))
        for t in ("I want a refund", "refund chahiye", "making charges refund not reflecting"):
            with self.subTest(t=t):
                self.assertNotEqual(_programmatic_intent_override(t), ("refund_status", 0.95))

    def test_route_states_locked_window_then_offers_callback_form(self):
        data = {"phone_number": "919812345678", "client_id": "kisna", "messages": {}}
        profile = {}
        with patch("kisna_chatbot.config.gupshup.get_callback_flow_id", return_value="flow"):
            stop = _route_resolved_intent(data, profile, "919812345678", "my refund hasn't come",
                                          [], "refund_status", 0.95)
        self.assertTrue(stop)
        text_item, form_item = data["bot_response"]
        self.assertEqual(REFUND_PROCESSING_TEXT, "10 business days")
        self.assertIn("10 business days", text_item["text"])
        self.assertEqual(text_item["_compose"], "refund_status")
        self.assertIn("10 business days", text_item["_pin"])
        self.assertEqual(form_item["flow"], "callback_request")
        self.assertEqual(profile["service_selected"], "callback")

    def test_size_exchange_phrases_are_action_hints_and_few_shots(self):
        for t in ("Can I exchange it for another size?", "can I exchange it for a different size"):
            self.assertTrue(_ACTION_INTENT_RE.search(t), t)
        self.assertIn('"Can I exchange it for another size?" -> returns_refund .9', kisna_classifier_intent)
        self.assertIn('"My refund hasn\'t come" -> refund_status .92', kisna_classifier_intent)

    def test_wrapper_rules(self):
        self.assertIn("NEVER call it for EMI, bank, credit-card or payment-method questions", _WRAPPER)
        self.assertIn('Just message me "I have a complaint" and I\'ll open\nthe complaint form for you.', _WRAPPER)


# ------------------------------------------------- localisation (Part 4)
class LocalisationPinsTests(unittest.TestCase):
    def _localize(self, item, language="hi"):
        data = {
            "messages": {"type": "text", "text": {"body": "x"}},
            "user_profile": {"language": language},
            "bot_response": [item],
        }

        async def fake_compose(key, text, *, pin=(), **kw):
            # A translator that keeps only the pinned tokens.
            return "MARKER " + " | ".join(pin)

        with patch.object(reply_composer, "compose", side_effect=fake_compose) as comp:
            asyncio.run(reply_composer.localize_bot_responses(data))
        return data["bot_response"][0], comp

    def test_callback_confirmation_keeps_id_date_slot_and_brand(self):
        (item,) = cba._build_confirmation(ID, "callback", preferred_date="2026-09-29",
                                          preferred_time="10-13", now=at(MON, 11))
        out, comp = self._localize(item)
        self.assertTrue(out["text"].startswith("MARKER"))
        for token in (ID, "29 September 2026", "10:00 AM–1:00 PM", "Kisna Diamond & Gold"):
            self.assertIn(token, out["text"])
        self.assertNotIn("_pin", out)
        self.assertEqual(comp.call_args.kwargs["language"], "hi")

    def test_complaint_confirmation_keeps_id_brand_and_sla(self):
        (item,) = ca._build_confirmation("KIS-CMP-20260928-A1B2")
        out, _ = self._localize(item)
        for token in ("KIS-CMP-20260928-A1B2", "Kisna Diamond & Gold", "1 working day"):
            self.assertIn(token, out["text"])

    def test_english_is_verbatim(self):
        (item,) = ca._build_confirmation("KIS-CMP-20260928-A1B2")
        expected = item["text"]
        out, comp = self._localize(item, language="en")
        comp.assert_not_called()
        self.assertEqual(out["text"], expected)

    def test_pre_form_text_becomes_the_flow_body(self):
        rm = ResponseManager()
        item = build_callback_flow_bot_response()
        with patch("kisna_chatbot.processors.response_manager.send_callback_request_flow",
                   return_value={"ok": True}) as send:
            rm._handle_flow("919812345678", item)
        self.assertEqual(send.call_args.kwargs["body_text"], form_copy.CALLBACK_PREFORM)


# ----------------------------------------------- dead code + workflow
class HousekeepingTests(unittest.TestCase):
    def test_store_visit_code_is_gone(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "kisna_chatbot/whatsapp_functions/flow/send_site_visit.py").exists())
        self.assertFalse((root / "kisna_chatbot/whatsapp_functions/flow/send_store_visit_datetime.py").exists())
        self.assertFalse(hasattr(FLowId, "SITE_VISIT"))
        self.assertFalse(hasattr(FLowId, "STORE_VISIT_DATETIME"))
        for path in (root / "kisna_chatbot").rglob("*.py"):
            self.assertNotIn("PIMS", path.read_text(encoding="utf-8"), str(path))

    def test_deploy_workflow_keeps_logs_and_rotates(self):
        wf = (Path(__file__).resolve().parents[1] / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")
        self.assertIn("/var/log/kisna", wf)
        self.assertIn("tail -n +11", wf)
        self.assertEqual(wf.count("--log-opt max-size=50m --log-opt max-file=5"), 2)
        self.assertLess(wf.index("docker logs kisna-backend >"), wf.index("docker rm kisna-backend"))


if __name__ == "__main__":
    unittest.main()
