# With uv, every target runs on Python 3.12 with PyYAML, the same as CI, whatever the system
# python3 is (macOS ships 3.9, which the cfo scripts refuse). Without uv, python3 is used as is.
UV := $(shell command -v uv 2>/dev/null)
ifdef UV
PYTHON ?= uv run --no-project --quiet --python 3.12 --with pyyaml python
else
PYTHON ?= python3
endif

.PHONY: help gen check validate versions claude-validate unit record test all

help:
	@echo "make gen              regenerate manifests, marketplaces, package.json, docs/CATALOG.md from kit.yaml"
	@echo "make check            fail if generated files are stale (what CI runs)"
	@echo "make validate         portability lint for skills and plugins"
	@echo "make versions         fail if a plugin changed since BASE (default origin/main) without a version bump"
	@echo "make claude-validate  run 'claude plugin validate --strict' on every plugin and the marketplace"
	@echo "make unit             unit tests for the scripts skills ship (QUALITY_FULL_SEEDS=1 runs every property-test seed)"
	@echo "make record           the same tests through the quality recorder; writes per-test time and outcome to RECORD_OUT"
	@echo "make all              gen + validate + claude-validate"

gen:
	$(PYTHON) tools/kitgen.py

check:
	$(PYTHON) tools/kitgen.py --check

validate:
	$(PYTHON) tools/validate.py

BASE ?= origin/main
versions:
	$(PYTHON) tools/check_versions.py --base $(BASE)

claude-validate:
	@command -v claude >/dev/null || { echo "claude CLI not found; skipping"; exit 0; }
	@set -e; for p in plugins/*/; do claude plugin validate --strict "$$p"; done
	claude plugin validate --strict .

test: check validate unit

unit:
	$(PYTHON) -m unittest discover -s tests

# The same suite, run as `make unit` runs it, with per-test time and outcome written for the
# quality books (lyddonb/quality). CI uses this and uploads the file.
RECORD_OUT ?= $(or $(RUNNER_TEMP),$(TMPDIR),/tmp)/test-results.jsonl
RECORD_WORKERS ?= 1
record:
	$(PYTHON) plugins/bstack/skills/qualitydirector/scripts/quality.py record tests --out "$(RECORD_OUT)" --repo agent-kit --workers $(RECORD_WORKERS)

all: gen validate claude-validate
