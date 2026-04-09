PYTHON = py

.PHONY: test lint typecheck coverage check run analyze watch paper backtest

# ── Quality ───────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest -v

lint:
	$(PYTHON) -m ruff check .

lint-fix:
	$(PYTHON) -m ruff check . --fix

typecheck:
	$(PYTHON) -m mypy . --no-error-summary

coverage:
	$(PYTHON) -m pytest --cov=. --cov-report=term-missing --cov-omit="tests/*"

# Run all checks in sequence
check: lint typecheck test

# ── App ───────────────────────────────────────────────────────────────────────
run:
	$(PYTHON) main.py

analyze:
	$(PYTHON) main.py analyze

watch:
	$(PYTHON) main.py watch

paper:
	$(PYTHON) main.py paper

backtest:
	$(PYTHON) main.py backtest
