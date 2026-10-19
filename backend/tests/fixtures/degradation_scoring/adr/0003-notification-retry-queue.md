---
status: proposed
scope: local
date: 2026-03-02
---
# ADR-0003: Local retry queue for notifications

## Context
Email and SMS providers fail intermittently.

## Decision
notification-service keeps a local retry queue instead of a shared broker.

## Consequences
Retries are invisible to other services.
