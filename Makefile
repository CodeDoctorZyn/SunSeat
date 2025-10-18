# SunDirect - Train Sun Exposure Advisor

.PHONY: help install dev run test clean build docker-build docker-run

# Default target
help:
	@echo "SunDirect - Train Sun Exposure Advisor"
	@echo ""
	@echo "Available targets:"
	@echo "  install      Install Python dependencies"
	@echo "  dev          Run development server with hot reload"
	@echo "  run          Run production server"
	@echo "  test         Run unit tests"
	@echo "  clean        Clean up temporary files" 
	@echo "  build        Build Docker image"
	@echo "  docker-run   Run Docker container"
	@echo "  docker-dev   Run Docker container with volume mount for development"

# Install dependencies
install:
	pip install --upgrade pip
	pip install -r requirements.txt

# Run development server
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run production server
run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run tests
test:
	python -m pytest tests/ -v

# Run tests with coverage
test-coverage:
	python -m pytest tests/ -v --cov=app --cov-report=html

# Clean temporary files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .coverage htmlcov/ .pytest_cache/

# Build Docker image
build:
	docker build -t sundirect:latest .

# Run Docker container
docker-run:
	docker run -p 8000:8000 \
		-e GTFS_DIR=/app/data/gtfs_sample \
		-e TIMEZONE=Australia/Melbourne \
		sundirect:latest

# Run Docker container with development volume mount
docker-dev:
	docker run -p 8000:8000 \
		-v $(PWD)/data:/app/data \
		-v $(PWD)/app:/app/app \
		-e GTFS_DIR=/app/data/gtfs_sample \
		-e TIMEZONE=Australia/Melbourne \
		sundirect:latest

# Format code
format:
	black app/ tests/
	isort app/ tests/

# Lint code
lint:
	flake8 app/ tests/
	mypy app/

# Setup development environment
setup-dev: install
	pip install black isort flake8 mypy pytest pytest-cov
	@echo "Development environment setup complete!"
	@echo "Run 'make dev' to start the development server"