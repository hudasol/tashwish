# Common tasks. Works with GNU make on Linux and macOS.
# On Windows without make, run the same commands directly, for example:
#   python -m pip install -e ".[api,dev]"
#   python -m pytest
#   python -m ruff check .
#   python -m tashwish.release.build
# Every recipe below is a plain python -m command for that reason.

PYTHON ?= python3
WEB_PORT ?= 8080
API_PORT ?= 8000

.PHONY: install install-locked test lint format build-release serve-web serve-api clean

install:
	$(PYTHON) -m pip install -e ".[api,dev]"

# Same, with the versions pinned in requirements-dev.lock (Python 3.12 or newer).
install-locked:
	$(PYTHON) -m pip install -c requirements-dev.lock -e ".[api,dev]"

test:
	$(PYTHON) -m pytest --cov=tashwish --cov-report=term-missing:skip-covered

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

# Rebuilds web/data and release/ from processed/. Pass options with BUILD_ARGS, for example
# make build-release BUILD_ARGS="--mode study_snapshot".
build-release:
	$(PYTHON) -m tashwish.release.build $(BUILD_ARGS)

serve-web:
	$(PYTHON) -m http.server $(WEB_PORT) --directory web

serve-api:
	$(PYTHON) -m tashwish.api --release-dir release --port $(API_PORT)

clean:
	rm -rf build dist .pytest_cache .ruff_cache .hypothesis .coverage htmlcov
	find . -name "*.egg-info" -type d -prune -exec rm -rf {} +
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
