# Development task runner for the Architecture Degradation Detector.
#
# Requires: GNU make, uv, npm (Node >= 22.22.0) and Docker with Compose v2.
# Run `make` or `make help` to list every target.

ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
.SHELLFLAGS := /c
endif

COMPOSE := docker compose -f backend/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help up down db-up db-down db-logs backend frontend dev install test lint

# Databases ------------------------------------------------------------------

## up: Start the PostgreSQL and Neo4j containers.
up: db-up

## down: Stop the PostgreSQL and Neo4j containers.
down: db-down

## db-up: Start the PostgreSQL and Neo4j containers in the background.
db-up:
	$(COMPOSE) up -d

## db-down: Stop and remove the PostgreSQL and Neo4j containers.
db-down:
	$(COMPOSE) down

## db-logs: Follow the logs of the database containers.
db-logs:
	$(COMPOSE) logs -f

# Applications ---------------------------------------------------------------

## backend: Run the FastAPI backend with autoreload.
backend:
	cd backend && uv run uvicorn app.main:app --reload

## frontend: Run the Vite dev server.
frontend:
	cd frontend && npm run dev

## dev: Run the backend and the frontend together, each in its own process.
ifeq ($(OS),Windows_NT)
dev:
	start "ADD backend" cmd /c "cd backend && uv run uvicorn app.main:app --reload"
	start "ADD frontend" cmd /c "cd frontend && npm run dev"
else
dev:
	cd backend && uv run uvicorn app.main:app --reload & \
	cd frontend && npm run dev & \
	wait
endif

# Project --------------------------------------------------------------------

## install: Install the backend and frontend dependencies.
install:
	cd backend && uv sync
	cd frontend && npm install

## test: Run the backend test suite.
test:
	cd backend && uv run pytest

## lint: Run the frontend linter.
lint:
	cd frontend && npm run lint

## help: Show this list of targets.
help:
	@echo Available targets:
	@echo   up        Start the PostgreSQL and Neo4j containers.
	@echo   down      Stop the PostgreSQL and Neo4j containers.
	@echo   db-logs   Follow the database container logs.
	@echo   backend   Run the FastAPI backend with autoreload.
	@echo   frontend  Run the Vite dev server.
	@echo   dev       Run the backend and the frontend together.
	@echo   install   Install the backend and frontend dependencies.
	@echo   test      Run the backend test suite.
	@echo   lint      Run the frontend linter.
