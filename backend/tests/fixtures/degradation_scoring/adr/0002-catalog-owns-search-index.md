---
status: superseded
scope: component
date: 2025-11-10
superseded_by: 0004-search-index-service
---
# ADR-0002: catalog-service owns the search index

## Context
Search results were stale because two services wrote the index.

## Decision
catalog-service owns the search index; search-service only reads it.

## Consequences
catalog-service grows; a later decision may split the index out again.
