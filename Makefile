.PHONY: install dev lint format test typecheck precommit docs

install:
	python3 -m pip install -e .

dev:
	python3 -m pip install -e ".[dev,test,docs]"
	pre-commit install

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src/uummannaq_ice

test:
	pytest --cov=uummannaq_ice --cov-report=term-missing

precommit:
	pre-commit run --all-files

docs:
	mkdocs serve
