.PHONY: .DEFAULT
.DEFAULT: help

PYINSTRUMENT_OUTFILE ?= .pyinstrument/gojeera-profile.html
PYINSTRUMENT_SESSION ?= .pyinstrument/gojeera-profile.pyisession

.PHONY: help
help:
	@fgrep -h "##" $(MAKEFILE_LIST) | sed -e 's/\(\:.*\#\#\)/\:\ /' | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

.PHONY: env
env: ##Prepare environment using uv (including development tools)
	uv sync --all-groups
.PHONY: lint
lint: ##Lint
	@uv run ruff format . --diff
	@uv run ruff check .

.PHONY: lint-fix
lint-fix: ##Fix linting
	@uv run ruff format
	@uv run ruff check --fix

.PHONY: type-check
type-check: ##Typecheck
	@uv run ty check

.PHONY: deadcode
deadcode: ##Detect deadcode
	@uv run vulture
	@uvx deadcode src tests scripts

.PHONY: compile
compile: ##Compiles code to check valid syntax
	@uv run python -m compileall -q .

.PHONY: check-css
check-css: ##Checks CSS
	@uv run python ./scripts/check_css.py

.PHONY: generate-static-svg
generate-static-svg: ##Generate all static SVG assets from the internal scenario map
	@python3 ./scripts/generate_static_svg.py

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
	-$(MAKE) generate-static-svg

.PHONY: profile
profile: ##Profile gojeera with pyinstrument
	@mkdir -p $(dir $(PYINSTRUMENT_OUTFILE))
	uv run --group debug pyinstrument -r pyisession -o $(PYINSTRUMENT_SESSION) -m gojeera.cli $(GOJEERA_ARGS)
	uv run --group debug pyinstrument --load $(PYINSTRUMENT_SESSION) -r html -o $(PYINSTRUMENT_OUTFILE)
	@printf '\nPyInstrument summary:\n\n'
	uv run --group debug pyinstrument --load $(PYINSTRUMENT_SESSION) -r text -p time=percent_of_total -p processor_options.filter_threshold=0.01
	@printf '\nSaved HTML report to %s\n' "$(PYINSTRUMENT_OUTFILE)"

.PHONY: profile-test
profile-test: ##Run profiling on tests
	uv run pytest -n auto tests --profile-svg

.PHONY: bump-dependencies
bump-dependencies: ##Bump project dependencies
	uvx uv-upx upgrade run
