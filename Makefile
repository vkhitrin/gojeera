.PHONY: .DEFAULT
.DEFAULT: help

.PHONY: help
help:
	@fgrep -h "##" $(MAKEFILE_LIST) | sed -e 's/\(\:.*\#\#\)/\:\ /' | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

.PHONY: env
env: ##Prepare environment using uv (including development tools)
	uv sync --all-groups

.PHONY: lint
lint: ##Lint using ruff
	@uv run ruff format . --diff
	@uv run ruff check .

.PHONY: type-check
type-check: ##Typecheck using ty
	@uv run ty check

.PHONY: deadcode
deadcode: ##Detect deadcode using vulture
	@uv run vulture

.PHONY: compile
compile: ##Compiles code to check valid syntax
	@uv run python -m compileall -q .

.PHONY: check-css
check-css: ##Checks CSS for unused classes and IDs
	@uv run python ./scripts/check_unused_css.py

.PHONY: analyze-codebase
analyze-codebase: ##Analyzes codebase
	-$(MAKE) lint
	-$(MAKE) type-check
	-$(MAKE) deadcode
	-$(MAKE) compile
	-$(MAKE) check-css

.PHONY: test
test: ##Run tests
	uv run pytest -n auto tests

.PHONY: test-update-snapshots
test-update-snapshots: ##Run tests and update snapshots
	uv run pytest -n auto tests --snapshot-update
