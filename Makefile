.PHONY: help setup run check test clean

help:
	@echo "Job Hunter"
	@echo ""
	@echo "  make setup  install dependencies and prepare the directories"
	@echo "  make run    set up if needed, then start OpenCode"
	@echo "  make check  report what setup still needs"
	@echo "  make test   run the repository checks and the Python tests"
	@echo "  make clean  remove .venv/ and node_modules/ (your data is untouched)"

setup:
	@./setup.sh

run: setup
	@./run.sh

check:
	@./setup.sh --check

test:
	@python3 tools/check_repo.py
	@python3 -m unittest discover -s tools/tests -t .

clean:
	@rm -rf .venv node_modules
	@echo "Removed .venv/ and node_modules/. resumes/, profiles/ and reports/ are untouched."
