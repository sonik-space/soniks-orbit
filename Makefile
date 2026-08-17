LOCAL_COMPOSE_FILE := docker_compose/local.yml
APP_SERVICE := orbit-api

.DEFAULT_GOAL := help

.PHONY: format lint test gate up up_build stop down down_v logs bash \
        makemigrations migrate downgrade demo help

format:
	uv run ruff format
	uv run ruff check --fix

# Без `ruff format --check`: код фаз 0 и 1 писался до появления ruff в проекте
# и выровнен руками. Прогон форматтера по всему репозиторию — отдельная правка
# отдельным коммитом, а не побочный эффект проверки.
lint:
	uv run ruff check

test:
	uv run pytest $(opts)

# Два числа, которые нельзя ухудшать. Гоняются после каждой правки,
# а не только перед коммитом (roadmap.md, фазы 0 и 1).
gate: test
	uv run python scripts/phase0/end_to_end.py 1527888
	uv run python scripts/phase1/sweep.py

up:
	docker compose -f $(LOCAL_COMPOSE_FILE) up -d

up_build:
	docker compose -f $(LOCAL_COMPOSE_FILE) up -d --build

stop:
	docker compose -f $(LOCAL_COMPOSE_FILE) stop

down:
	docker compose -f $(LOCAL_COMPOSE_FILE) down

down_v:
	docker compose -f $(LOCAL_COMPOSE_FILE) down -v

logs:
	docker logs $(APP_SERVICE) -f

bash:
	docker exec -it $(APP_SERVICE) bash

makemigrations:
ifndef m
	$(error Параметр "m" обязателен. Использование: make makemigrations m="Описание")
endif
	POSTGRES__HOST=localhost POSTGRES__PORT=5434 PYTHONPATH=src \
		uv run alembic revision --autogenerate -m="$(m)"

migrate:
	docker exec -it $(APP_SERVICE) sh -c "alembic upgrade head"

downgrade:
	docker exec -it $(APP_SERVICE) sh -c "alembic downgrade -1"

demo:
	./scripts/phase2/demo.sh $(opts)

help:
	@echo "Использование: make [команда]"
	@echo ""
	@echo "  format           ruff format + autofix"
	@echo "  lint             ruff format --check + ruff check"
	@echo "  test             pytest       (opts=\"<опции pytest>\")"
	@echo "  gate             тесты плюс два числа: RMS 0.0250 кГц на 1527888"
	@echo "                   и покрытие 11 из 23. Ухудшать нельзя"
	@echo ""
	@echo "  up / up_build    поднять контейнеры (с пересборкой)"
	@echo "  stop / down      остановить / удалить контейнеры"
	@echo "  down_v           удалить вместе с volume'ами"
	@echo "  logs / bash      логи / шелл в $(APP_SERVICE)"
	@echo ""
	@echo "  makemigrations   создать миграцию, m=\"Описание\" обязателен"
	@echo "  migrate          применить миграции в контейнере"
	@echo "  downgrade        откатить последнюю миграцию"
	@echo ""
	@echo "  demo             сессия по наблюдению 1527888 через HTTP"
