"""kisna_chatbot/utils/media_store.py — the Backblaze B2 adapter.

is_configured() is the feature's on/off switch (no separate .env flag): every
put_bytes/presign_get call must no-op cleanly when B2 credentials aren't set.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.utils import media_store  # noqa: E402

_ALL_B2_VARS = ("B2_ENDPOINT", "B2_REGION", "B2_KEY_ID", "B2_APPLICATION_KEY", "B2_BUCKET")


def _clear_b2_env():
    return patch.dict(os.environ, {k: "" for k in _ALL_B2_VARS})


def _set_b2_env():
    return patch.dict(
        os.environ,
        {
            "B2_ENDPOINT": "https://s3.us-west-004.backblazeb2.com",
            "B2_REGION": "us-west-004",
            "B2_KEY_ID": "key123",
            "B2_APPLICATION_KEY": "appkey123",
            "B2_BUCKET": "kisna-media",
        },
    )


class IsConfiguredTests(unittest.TestCase):
    def test_all_unset_is_not_configured(self):
        with _clear_b2_env():
            self.assertFalse(media_store.is_configured())

    def test_all_set_is_configured(self):
        with _set_b2_env():
            self.assertTrue(media_store.is_configured())

    def test_one_missing_is_not_configured(self):
        with _set_b2_env(), patch.dict(os.environ, {"B2_BUCKET": ""}):
            self.assertFalse(media_store.is_configured())


class MaxBytesTests(unittest.TestCase):
    def test_default(self):
        with patch.dict(os.environ, {"KISNA_MEDIA_MAX_BYTES": ""}, clear=False):
            os.environ.pop("KISNA_MEDIA_MAX_BYTES", None)
            self.assertEqual(media_store.max_bytes(), 20 * 1024 * 1024)

    def test_override(self):
        with patch.dict(os.environ, {"KISNA_MEDIA_MAX_BYTES": "1000"}):
            self.assertEqual(media_store.max_bytes(), 1000)

    def test_malformed_falls_back_to_default(self):
        with patch.dict(os.environ, {"KISNA_MEDIA_MAX_BYTES": "not-a-number"}):
            self.assertEqual(media_store.max_bytes(), 20 * 1024 * 1024)


class PutBytesTests(unittest.TestCase):
    def test_not_configured_returns_false_without_touching_client(self):
        with _clear_b2_env(), patch.object(media_store, "_client") as mock_client:
            ok = media_store.put_bytes(b"data", "k", "image/jpeg")
            self.assertFalse(ok)
            mock_client.assert_not_called()

    def test_success_calls_put_object(self):
        fake_client = MagicMock()
        with _set_b2_env(), patch.object(media_store, "_client", return_value=fake_client):
            ok = media_store.put_bytes(b"data", "kisna/inbound/x.jpg", "image/jpeg")
        self.assertTrue(ok)
        fake_client.put_object.assert_called_once()
        kwargs = fake_client.put_object.call_args.kwargs
        self.assertEqual(kwargs["Bucket"], "kisna-media")
        self.assertEqual(kwargs["Key"], "kisna/inbound/x.jpg")
        self.assertEqual(kwargs["Body"], b"data")
        self.assertEqual(kwargs["ContentType"], "image/jpeg")

    def test_exception_returns_false_never_raises(self):
        fake_client = MagicMock()
        fake_client.put_object.side_effect = RuntimeError("boom")
        with _set_b2_env(), patch.object(media_store, "_client", return_value=fake_client):
            ok = media_store.put_bytes(b"data", "k", "image/jpeg")
        self.assertFalse(ok)


class PresignGetTests(unittest.TestCase):
    def test_not_configured_returns_none(self):
        with _clear_b2_env():
            self.assertIsNone(media_store.presign_get("k", 900))

    def test_success_returns_url(self):
        fake_client = MagicMock()
        fake_client.generate_presigned_url.return_value = "https://b2.example/signed"
        with _set_b2_env(), patch.object(media_store, "_client", return_value=fake_client):
            url = media_store.presign_get("kisna/outbound/x.pdf", 900)
        self.assertEqual(url, "https://b2.example/signed")
        kwargs = fake_client.generate_presigned_url.call_args.kwargs
        self.assertEqual(kwargs["Params"]["Key"], "kisna/outbound/x.pdf")
        self.assertEqual(kwargs["ExpiresIn"], 900)

    def test_exception_returns_none_never_raises(self):
        fake_client = MagicMock()
        fake_client.generate_presigned_url.side_effect = RuntimeError("boom")
        with _set_b2_env(), patch.object(media_store, "_client", return_value=fake_client):
            self.assertIsNone(media_store.presign_get("k", 900))


class ClientConstructionTests(unittest.TestCase):
    """B2 differs from R2 in exactly two ways: an explicit endpoint (not
    derived from an account id) and a real region (not a wildcard). Lock
    both in so a future provider swap can't silently regress signing."""

    def test_client_wired_from_b2_env_vars(self):
        media_store._client.cache_clear()
        captured = {}

        class _FakeBoto3:
            @staticmethod
            def client(service, **kwargs):
                captured["service"] = service
                captured.update(kwargs)
                return MagicMock()

        with _set_b2_env(), patch.dict("sys.modules", {"boto3": _FakeBoto3}):
            media_store._get_client()

        self.assertEqual(captured["service"], "s3")
        self.assertEqual(captured["endpoint_url"], "https://s3.us-west-004.backblazeb2.com")
        self.assertEqual(captured["region_name"], "us-west-004")
        self.assertEqual(captured["aws_access_key_id"], "key123")
        self.assertEqual(captured["aws_secret_access_key"], "appkey123")
        media_store._client.cache_clear()


if __name__ == "__main__":
    unittest.main()
