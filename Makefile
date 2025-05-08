# Variables
IMAGE_NAME ?= framjet/eso-cluster-secret-store-per-ns
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LATEST_TAG = latest

# Docker build arguments
DOCKER_BUILD_ARGS ?= --build-arg VERSION=$(VERSION)

.PHONY: all build push clean test lint help

all: build

help: ## Display this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk -F ':|##' '/^[^\t].+?:.*?##/ { printf "  %-20s %s\n", $$1, $$NF }' $(MAKEFILE_LIST)

build: ## Build the Docker image
	docker build $(DOCKER_BUILD_ARGS) -t $(IMAGE_NAME):$(VERSION) -t $(IMAGE_NAME):$(LATEST_TAG) .

build-no-cache: ## Build the Docker image without using cache
	docker build --no-cache $(DOCKER_BUILD_ARGS) -t $(IMAGE_NAME):$(VERSION) -t $(IMAGE_NAME):$(LATEST_TAG) .

push: ## Push the Docker image to registry
	docker push $(IMAGE_NAME):$(VERSION)
	docker push $(IMAGE_NAME):$(LATEST_TAG)

clean: ## Remove local Docker images
	docker rmi $(IMAGE_NAME):$(VERSION) || true
	docker rmi $(IMAGE_NAME):$(LATEST_TAG) || true

test: ## Run tests
	python -m pytest tests/

lint: ## Run linting
	flake8 .
	black --check .
	isort --check-only .

format: ## Format code
	black .
	isort .

# Development targets
dev-install: ## Install development dependencies
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

dev-run: ## Run the operator locally
	python k8s_operator.py

# Docker development targets
docker-run: ## Run the Docker image locally
	docker run --rm -it \
		-v ~/.kube/config:/root/.kube/config \
		$(IMAGE_NAME):$(VERSION)

docker-shell: ## Run a shell in the Docker image
	docker run --rm -it \
		-v ~/.kube/config:/root/.kube/config \
		--entrypoint /bin/bash \
		$(IMAGE_NAME):$(VERSION) 