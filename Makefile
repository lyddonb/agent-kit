PYTHON ?= python3

.PHONY: help gen check validate claude-validate test all

help:
	@echo "make gen              regenerate manifests, marketplaces, package.json, docs/CATALOG.md from kit.yaml"
	@echo "make check            fail if generated files are stale (what CI runs)"
	@echo "make validate         portability lint for skills and plugins"
	@echo "make claude-validate  run 'claude plugin validate --strict' on every plugin and the marketplace"
	@echo "make all              gen + validate + claude-validate"

gen:
	$(PYTHON) tools/kitgen.py

check:
	$(PYTHON) tools/kitgen.py --check

validate:
	$(PYTHON) tools/validate.py

claude-validate:
	@command -v claude >/dev/null || { echo "claude CLI not found; skipping"; exit 0; }
	@set -e; for p in plugins/*/; do claude plugin validate --strict "$$p"; done
	claude plugin validate --strict .

test: check validate

all: gen validate claude-validate
