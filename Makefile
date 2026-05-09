# OzBargainer Orchestration
# Alignment: §4.2, §4.9, §4.10

.PHONY: help start stop restart logs status backup test shell

# Default target: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

start: ## Start host bridge and docker container
	@./scripts/bridge.sh start
	@docker compose up -d

stop: ## Stop docker container and host bridge
	@docker compose down
	@./scripts/bridge.sh stop

restart: ## Restart host bridge and docker container
	@$(MAKE) stop
	@$(MAKE) start

logs: ## Tail container logs
	docker compose logs -f monitor

status: ## Show status of bridge and container
	@echo "--- SYSTEM STATUS ---"
	@./scripts/bridge.sh status || true
	@echo -n "CONTAINER: "
	@if [ "$$(docker compose ps --quiet monitor)" ]; then \
		echo "RUNNING ($$(docker compose ps monitor --format '{{.Status}}'))"; \
	else \
		echo "STOPPED"; \
	fi

backup: ## Trigger database backup
	./scripts/backup_db.sh

test: ## Run tests within a temporary container
	docker compose run --rm monitor pytest tests/ -v

shell: ## Open shell in the running monitor container
	docker compose exec monitor bash

clean: ## Remove temporary files and docker artifacts
	docker compose down --rmi local --volumes --remove-orphans
	rm -f chrome_startup.log
