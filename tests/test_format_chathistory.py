import unittest

from kisna_chatbot.utils.format_chathistory import (
    DEFAULT_HISTORY_WINDOW,
    format_recent_history_str,
    get_recent_history,
    trim_chat_history,
)


class GetRecentHistoryTests(unittest.TestCase):
    def test_empty_profile(self):
        self.assertEqual(get_recent_history({}), [])
        self.assertEqual(get_recent_history({"chat_history": None}), [])

    def test_slices_to_n(self):
        history = [{"role": "user", "content": f"m{i}"} for i in range(12)]
        profile = {"chat_history": history}
        recent = get_recent_history(profile, 8)
        self.assertEqual(len(recent), 8)
        self.assertEqual(recent[0]["content"], "m4")
        self.assertEqual(recent[-1]["content"], "m11")

    def test_default_window_is_eight(self):
        self.assertEqual(DEFAULT_HISTORY_WINDOW, 8)


class FormatRecentHistoryStrTests(unittest.TestCase):
    def test_formats_roles(self):
        profile = {
            "chat_history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ]
        }
        result = format_recent_history_str(profile, 8)
        self.assertEqual(result, "User: hello\nAssistant: hi there")

    def test_empty_history(self):
        self.assertEqual(format_recent_history_str({}), "")


class TrimChatHistoryTests(unittest.TestCase):
    def test_no_trim_when_under_limit(self):
        history = [{"role": "user", "content": "a"}]
        self.assertEqual(trim_chat_history(history, 50), history)

    def test_trims_to_last_max(self):
        history = [{"role": "user", "content": f"m{i}"} for i in range(60)]
        trimmed = trim_chat_history(history, 50)
        self.assertEqual(len(trimmed), 50)
        self.assertEqual(trimmed[0]["content"], "m10")
        self.assertEqual(trimmed[-1]["content"], "m59")


if __name__ == "__main__":
    unittest.main()
