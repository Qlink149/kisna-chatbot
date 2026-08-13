.PHONY: test test-live regression prompt-budget help

help:
	@echo "test           run the hermetic test suite (no network)"
	@echo "test-live      run only tests that need a real provider"
	@echo "prompt-budget  check prompt size and intent balance only"
	@echo "regression     RELEASE GATE - live classifier regression suite"

test:
	pytest

test-live:
	pytest -m live

prompt-budget:
	pytest tests/test_prompt_budget.py tests/test_prompt_balance.py -q

# Release gate. Hits the live model, so it is not part of `make test`.
# Ship only if every bucket holds at 100% - see README.
regression:
	python scripts/run_classifier_regression.py --label pre-release
