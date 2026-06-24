.PHONY: dev test test-unit test-integration test-e2e lint format \
        docker-build docker-up docker-down run-api run-ui clean

dev:
	pip install -r requirements.txt
	test -f .env || cp .env.example .env
	mkdir -p data
	@echo "Done. The copilot needs Ollama running (make docker-up) for /copilot/ask; solver routes work without it."

test:
	pytest

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

test-e2e:
	pytest tests/e2e -v

lint:
	ruff check src tests
	mypy src --ignore-missing-imports

format:
	ruff check --fix src tests
	ruff format src tests

run-api:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

run-ui:
	python src/ui/app.py

docker-build:
	docker build -f deployment/docker/Dockerfile -t supplyiq-api:latest .
	docker build -f deployment/docker/Dockerfile.ui -t supplyiq-ui:latest .

docker-up:
	docker compose -f deployment/docker/docker-compose.yml up -d

docker-down:
	docker compose -f deployment/docker/docker-compose.yml down

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage .mypy_cache .ruff_cache
