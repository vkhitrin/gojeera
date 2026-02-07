#!/usr/bin/env bash
# Run pytest with arguments, defaulting to 'tests' if no arguments provided

if [ $# -eq 0 ]; then
	uv run pytest tests
else
	uv run pytest "$@"
fi
