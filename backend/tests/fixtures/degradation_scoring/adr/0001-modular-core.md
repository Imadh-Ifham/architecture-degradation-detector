---
status: accepted
scope: system
date: 2025-09-01
---
# ADR-0001: Modular core

## Context
Core services had started calling each other in loops.

## Decision
Core services depend only on common-lib and on their own data. No core service calls
another core service synchronously in a cycle.

## Consequences
Cycles between core services are violations of this decision.
