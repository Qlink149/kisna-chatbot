"""scripts/prune_registry.py -- the Vultr registry cleanup used by deploy-prod.yml.

Locks in the fix for the deploy that failed with every DELETE returning 403:
the loop must attempt every candidate tag (a bad credential or one bad digest
must not stop the other 40+ from being cleaned up), and only report/exit at
the end -- not abort on the first failure.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from scripts import prune_registry  # noqa: E402


def _fake_session(tags, digests, delete_results):
    """digests: {tag: digest}. delete_results: {digest: (status, body)}."""
    sess = MagicMock()

    def get(url, **_kw):
        resp = MagicMock()
        if url.endswith("/tags/list"):
            resp.json.return_value = {"tags": tags}
            resp.raise_for_status = MagicMock()
        else:
            tag = url.rsplit("/", 1)[-1]
            resp.headers = {"Docker-Content-Digest": digests[tag]}
            resp.raise_for_status = MagicMock()
        return resp

    def delete(url, **_kw):
        digest = url.rsplit("/", 1)[-1]
        status, body = delete_results.get(digest, (202, ""))
        resp = MagicMock()
        resp.status_code = status
        resp.text = body
        return resp

    sess.get.side_effect = get
    sess.delete.side_effect = delete
    return sess


class DeleteDigestTests(unittest.TestCase):
    def test_returns_status_and_body(self):
        sess = MagicMock()
        sess.delete.return_value = MagicMock(status_code=403, text="Forbidden: insufficient scope")
        status, body = prune_registry.delete_digest(sess, "sha256:abc")
        self.assertEqual(status, 403)
        self.assertIn("Forbidden", body)


class MainExecuteResilienceTests(unittest.TestCase):
    """The core fix: don't raise SystemExit on the first bad delete."""

    def _run_main(self, tags, digests, delete_results, ranks):
        sess = _fake_session(tags, digests, delete_results)
        with (
            patch.object(prune_registry, "registry_auth", return_value=("u", "p")),
            patch.object(prune_registry, "session", return_value=sess),
            patch.object(prune_registry, "git_sha_order", return_value=ranks),
            patch("sys.argv", ["prune_registry.py", "--keep", "1", "--execute"]),
        ):
            prune_registry.main()

    def test_continues_past_a_failure_and_attempts_every_tag(self):
        tags = ["latest", "a" * 40,
                "b" * 40,
                "c" * 40]
        digests = {
            "latest": "sha256:keep",
            tags[1]: "sha256:keep",  # newest SHA shares latest's digest -- kept
            tags[2]: "sha256:del1",
            tags[3]: "sha256:del2",
        }
        # newest-first rank: tags[1] > tags[2] > tags[3]
        ranks = {tags[1]: 3, tags[2]: 2, tags[3]: 1}
        delete_results = {
            "sha256:del1": (403, "Forbidden: requires delete permission"),
            "sha256:del2": (202, ""),
        }
        sess = _fake_session(tags, digests, delete_results)
        with (
            patch.object(prune_registry, "registry_auth", return_value=("u", "p")),
            patch.object(prune_registry, "session", return_value=sess),
            patch.object(prune_registry, "git_sha_order", return_value=ranks),
            patch("sys.argv", ["prune_registry.py", "--keep", "1", "--execute"]),
        ):
            with self.assertRaises(SystemExit):
                prune_registry.main()

        # Both delete-candidate digests must have been attempted (del2's
        # successful delete is not skipped just because del1 failed first).
        deleted_digests = {c.args[0].rsplit("/", 1)[-1] for c in sess.delete.call_args_list}
        self.assertEqual(deleted_digests, {"sha256:del1", "sha256:del2"})

    def test_all_success_does_not_raise(self):
        tags = ["latest", "a" * 40,
                "b" * 40]
        digests = {"latest": "sha256:keep", tags[1]: "sha256:keep", tags[2]: "sha256:del1"}
        ranks = {tags[1]: 2, tags[2]: 1}
        delete_results = {"sha256:del1": (202, "")}
        sess = _fake_session(tags, digests, delete_results)
        with (
            patch.object(prune_registry, "registry_auth", return_value=("u", "p")),
            patch.object(prune_registry, "session", return_value=sess),
            patch.object(prune_registry, "git_sha_order", return_value=ranks),
            patch("sys.argv", ["prune_registry.py", "--keep", "1", "--execute"]),
        ):
            prune_registry.main()  # must not raise

    def test_kept_digest_is_never_deleted_even_if_also_an_old_tag(self):
        # Two SHA tags share one digest (e.g. a no-op rebuild): the older one
        # would normally be a delete candidate, but its digest is also
        # `latest`'s -- deleting it would untag latest too.
        tags = ["latest", "a" * 40,
                "b" * 40]
        digests = {"latest": "sha256:shared", tags[1]: "sha256:shared", tags[2]: "sha256:shared"}
        ranks = {tags[1]: 2, tags[2]: 1}
        sess = _fake_session(tags, digests, {})
        with (
            patch.object(prune_registry, "registry_auth", return_value=("u", "p")),
            patch.object(prune_registry, "session", return_value=sess),
            patch.object(prune_registry, "git_sha_order", return_value=ranks),
            patch("sys.argv", ["prune_registry.py", "--keep", "1", "--execute"]),
        ):
            prune_registry.main()
        sess.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
