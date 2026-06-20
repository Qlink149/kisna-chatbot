import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.database.db_utils import MAX_CHAT_HISTORY, save_to_mongo


class SaveToMongoHistoryCapTests(unittest.TestCase):
    @patch("kisna_chatbot.database.db_utils.users")
    def test_trims_chat_history_to_max(self, mock_users):
        mock_users.find_one_and_update.return_value = {"phone_number": "919999999999"}

        long_history = [
            {"role": "user", "content": f"m{i}", "timestamp": i} for i in range(60)
        ]
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "messages": {"type": "text", "text": {"body": "hello"}},
            "bot_response": [{"type": "text", "text": "hi"}],
            "user_profile": {"chat_history": long_history},
        }

        with patch(
            "kisna_chatbot.database.db_utils.format_chat_history",
            return_value=[
                {"role": "user", "content": "hello", "timestamp": 99},
                {"role": "assistant", "content": "hi", "timestamp": 99},
            ],
        ):
            save_to_mongo(data)

        saved_profile = mock_users.find_one_and_update.call_args[0][1]["$set"]
        self.assertLessEqual(len(saved_profile["chat_history"]), MAX_CHAT_HISTORY)
        self.assertEqual(len(saved_profile["chat_history"]), MAX_CHAT_HISTORY)
        self.assertEqual(saved_profile["chat_history"][-2]["content"], "hello")


if __name__ == "__main__":
    unittest.main()
