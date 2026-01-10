.PHONY: help
help:
	@echo "Available targets:"
	@echo "  env                        - Synchronize the uv environment"
	@echo "  install_pre_commit_hooks   - Install pre-commit hooks"
	@echo "  lint                       - Lint the code"
	@echo "  lint-fix                   - Lint the code and apply fixes"
	@echo "  test                       - Run tests"

.PHONY: env
env:
	uv sync --all-groups

.PHONY: install_pre_commit_hooks
install_pre_commit_hooks:
	pre-commit install -t pre-commit
	pre-commit install -t pre-push

.PHONY: lint
lint:
	mkdir -p /tmp/artifacts
	ruff format . --diff
	ruff check .
	uv run mypy --version
	uv run mypy --cache-dir /dev/null --junit-xml /tmp/artifacts/mypy.xml src

.PHONY: lint-fix
lint-fix:
	ruff format .
	ruff check . --fix

.PHONY: test
test:
	uv run --no-sync pytest src/gojeera
