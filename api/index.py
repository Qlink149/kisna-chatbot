"""Vercel serverless entrypoint for FastAPI (testing only).

Text-only flow branch: main WhatsApp menu removed from greetings and fallbacks.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path (kisna_chatbot package lives beside api/).
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from kisna_chatbot.main import app
