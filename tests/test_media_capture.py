"""kisna_chatbot/processors/media_capture.py — copy-on-receipt inbound capture.

Every failure mode must return None and never raise: the caller (main.py)
falls through to exactly today's behaviour on any None.
"""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

import httpx  # noqa: E402

from kisna_chatbot.processors import media_capture  # noqa: E402


def _image_message(url="https://filemanager.gupshup.io/wa/x/media/1", caption=None):
    payload = {"id": "media1", "mime_type": "image/jpeg", "url": url, "sha256": "abc"}
    if caption is not None:
        payload["caption"] = caption
    return {"type": "image", "image": payload}


class _StreamCtx:
    """Minimal async context manager mimicking httpx.AsyncClient.stream()."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


def _fake_response(chunks: list[bytes], status_ok=True):
    resp = MagicMock()
    if status_ok:
        resp.raise_for_status = MagicMock()
    else:
        req = httpx.Request("GET", "https://x")
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=req, response=MagicMock(status_code=404))
        )

    async def aiter_bytes():
        for c in chunks:
            yield c

    resp.aiter_bytes = aiter_bytes
    return resp


def _mock_async_client(response=None, raise_exc=None):
    client = MagicMock()

    def stream(method, url):
        if raise_exc:
            raise raise_exc
        return _StreamCtx(response)

    client.stream = stream
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class CaptureInboundMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_media_type_returns_none(self):
        result = await media_capture.capture_inbound_media({"type": "text", "text": {"body": "hi"}})
        self.assertIsNone(result)

    async def test_r2_not_configured_returns_none(self):
        with patch.object(media_capture.media_store, "is_configured", return_value=False):
            result = await media_capture.capture_inbound_media(_image_message())
        self.assertIsNone(result)

    async def test_missing_url_returns_none(self):
        with patch.object(media_capture.media_store, "is_configured", return_value=True):
            result = await media_capture.capture_inbound_media(
                {"type": "image", "image": {"id": "x", "mime_type": "image/jpeg"}}
            )
        self.assertIsNone(result)

    async def test_successful_capture_returns_media_dict(self):
        resp = _fake_response([b"abc", b"def"])
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch.object(
            media_capture.media_store, "put_bytes", return_value=True
        ) as mock_put, patch(
            "httpx.AsyncClient", return_value=_mock_async_client(response=resp)
        ):
            result = await media_capture.capture_inbound_media(_image_message(caption="my ring"))

        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["mime"], "image/jpeg")
        self.assertEqual(result["caption"], "my ring")
        self.assertEqual(result["size"], 6)
        self.assertEqual(result["source"], "inbound")
        self.assertTrue(result["b2_key"].startswith("kisna/inbound/"))
        self.assertTrue(result["b2_key"].endswith(".jpg"))
        mock_put.assert_called_once()

    async def test_fetch_timeout_returns_none(self):
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch(
            "httpx.AsyncClient",
            return_value=_mock_async_client(raise_exc=httpx.TimeoutException("timeout")),
        ):
            result = await media_capture.capture_inbound_media(_image_message())
        self.assertIsNone(result)

    async def test_fetch_404_returns_none(self):
        resp = _fake_response([], status_ok=False)
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch(
            "httpx.AsyncClient", return_value=_mock_async_client(response=resp)
        ):
            result = await media_capture.capture_inbound_media(_image_message())
        self.assertIsNone(result)

    async def test_oversized_media_rejected_before_upload(self):
        resp = _fake_response([b"x" * 10])
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch.object(
            media_capture.media_store, "max_bytes", return_value=5
        ), patch.object(media_capture.media_store, "put_bytes") as mock_put, patch(
            "httpx.AsyncClient", return_value=_mock_async_client(response=resp)
        ):
            result = await media_capture.capture_inbound_media(_image_message())
        self.assertIsNone(result)
        mock_put.assert_not_called()

    async def test_upload_failure_returns_none(self):
        resp = _fake_response([b"abc"])
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch.object(
            media_capture.media_store, "put_bytes", return_value=False
        ), patch("httpx.AsyncClient", return_value=_mock_async_client(response=resp)):
            result = await media_capture.capture_inbound_media(_image_message())
        self.assertIsNone(result)

    async def test_document_captures_filename(self):
        payload = {
            "id": "d1",
            "mime_type": "application/pdf",
            "url": "https://filemanager.gupshup.io/wa/x/media/2",
            "filename": "quote.pdf",
        }
        resp = _fake_response([b"%PDF"])
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch.object(
            media_capture.media_store, "put_bytes", return_value=True
        ), patch("httpx.AsyncClient", return_value=_mock_async_client(response=resp)):
            result = await media_capture.capture_inbound_media({"type": "document", "document": payload})
        self.assertEqual(result["kind"], "document")
        self.assertEqual(result["filename"], "quote.pdf")

    async def test_audio_has_no_caption_field_required(self):
        payload = {"id": "a1", "mime_type": "audio/ogg; codecs=opus", "url": "https://x/media/3"}
        resp = _fake_response([b"OggS"])
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch.object(
            media_capture.media_store, "put_bytes", return_value=True
        ), patch("httpx.AsyncClient", return_value=_mock_async_client(response=resp)):
            result = await media_capture.capture_inbound_media({"type": "audio", "audio": payload})
        self.assertEqual(result["kind"], "audio")
        self.assertIsNone(result["caption"])

    async def test_unexpected_exception_returns_none(self):
        with patch.object(media_capture.media_store, "is_configured", return_value=True), patch(
            "httpx.AsyncClient", side_effect=RuntimeError("boom")
        ):
            result = await media_capture.capture_inbound_media(_image_message())
        self.assertIsNone(result)

    async def test_non_dict_messages_returns_none(self):
        result = await media_capture.capture_inbound_media(None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
