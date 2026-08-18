# repo-root conftest
import os
import sys

# Ensure the project root is on sys.path so 'import kisna_chatbot' works
# regardless of how pytest is invoked.
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
