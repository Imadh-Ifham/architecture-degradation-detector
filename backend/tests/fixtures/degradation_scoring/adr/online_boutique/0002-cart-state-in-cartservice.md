---
status: accepted
scope: component
date: 2024-03-01
---
# ADR-0002: Cart state stays inside cartservice

**Fixture.** Hand-written stand-in for T21, not a decision of the Online Boutique project.

## Context
The cart is stored in Redis (redis-cart).

## Decision
Only cartservice reads or writes cart state; other services use its gRPC API.

## Consequences
Coupling that reaches into cart state is a violation of this decision.
