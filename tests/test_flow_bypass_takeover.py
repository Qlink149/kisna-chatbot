"""While a human agent has a conversation taken over, a complaint / callback /
video-call Flow submission must still be registered — it is a structured
record, not chat the agent answers. Every other message stays silent.

Real bug: +91xxxxxx4178 submitted the complaint form 2.5 h into an un-released
takeover; the pipeline was skipped, so no complaints row, no Clara event,
nothing on the dashboard.
"""

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot import main as m  # noqa: E402
from kisna_chatbot.models.enums import FLowId  # noqa: E402

_COMPLAINT_TOKEN = FLowId.DAMAGE_COMPLAINT.value  # built-in fallback, no env needed
_CALLBACK_TOKEN = "flow_cb_bypass_test"
_VIDEOCALL_TOKEN = "flow_vc_bypass_test"


def _nfm(flow_token: str, **fields) -> dict:
    return {
        "type": "interactive",
        "from": "919999999999",
        "id": "wamid.x",
        "interactive": {
            "nfm_reply": {"response_json": json.dumps({"flow_token": flow_token, **fields})}
        },
    }


class TrackedFlowDetectorTests(unittest.TestCase):
    # Other test modules hard-set KISNA_CALLBACK_FLOW_ID / VIDEOCALL at import,
    # and _callback_flow_ids() reads os.getenv live -- pin them here so this
    # file is order-independent.
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {
                "KISNA_CALLBACK_FLOW_ID": _CALLBACK_TOKEN,
                "KISNA_VIDEOCALL_FLOW_ID": _VIDEOCALL_TOKEN,
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_complaint_flow_reply_is_tracked(self):
        self.assertTrue(
            m._is_tracked_flow_submission(
                _nfm(_COMPLAINT_TOKEN, complaint_type="1_Order_Related", issue_description="x")
            )
        )

    def test_callback_flow_reply_is_tracked(self):
        self.assertTrue(m._is_tracked_flow_submission(_nfm(_CALLBACK_TOKEN)))

    def test_videocall_flow_reply_is_tracked(self):
        self.assertTrue(m._is_tracked_flow_submission(_nfm(_VIDEOCALL_TOKEN)))

    def test_plain_text_is_not_tracked(self):
        self.assertFalse(
            m._is_tracked_flow_submission({"type": "text", "text": {"body": "hi"}})
        )

    def test_button_reply_is_not_tracked(self):
        self.assertFalse(
            m._is_tracked_flow_submission(
                {"type": "interactive", "interactive": {"button_reply": {"title": "Yes"}}}
            )
        )

    def test_unknown_flow_token_is_not_tracked(self):
        self.assertFalse(m._is_tracked_flow_submission(_nfm("999000999000999")))

    def test_missing_interactive_is_not_tracked(self):
        self.assertFalse(m._is_tracked_flow_submission({"type": "image", "image": {"id": "x"}}))

    def test_malformed_response_json_is_not_tracked(self):
        self.assertFalse(
            m._is_tracked_flow_submission(
                {"type": "interactive", "interactive": {"nfm_reply": {"response_json": "{bad"}}}
            )
        )


if __name__ == "__main__":
    unittest.main()
