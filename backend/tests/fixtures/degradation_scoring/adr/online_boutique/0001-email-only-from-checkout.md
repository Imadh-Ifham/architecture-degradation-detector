---
status: accepted
scope: system
date: 2024-03-01
---
# ADR-0001: Email is sent only by checkout

**Fixture.** Hand-written stand-in for T21, not a decision of the Online Boutique project.

## Context
Order confirmation emails must go out once per order.

## Decision
Only checkoutservice calls emailservice. emailservice takes no new callers or duties.

## Consequences
New dependencies on emailservice are violations of this decision.
