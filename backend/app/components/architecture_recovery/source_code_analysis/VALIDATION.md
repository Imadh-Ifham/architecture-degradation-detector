# Source code analysis: Online Boutique validation

Validated on the Google Online Boutique working tree at commit
`38e7348eb289eb5b87c0c6e8cb19ced0449dc389`, through the real pipeline:
repository inventory -> manifest analysis -> component discovery -> dependency
resolution -> source code analysis. No expected relationship was hardcoded in
the analyzer.

## Pipeline input

| Stage | Result |
| --- | --- |
| Repository inventory | 357 files, 20 candidate components |
| Manifest analysis | 78 files, 360 resources, 359 relationships, 52 endpoints |
| Component discovery | 13 components, 102 artifacts |
| Dependency resolution | 17 resolved relationships |
| Source code analysis | 37 source files across 12 components |

## Source findings

| Metric | Value |
| --- | --- |
| Resolved findings | 17 |
| Unresolved findings | 1 |
| Ambiguous findings | 0 |
| Corroborated dependency relationships | 17 |
| Evidence entries | 56 |
| Diagnostics | 7 |

| Finding type | Count |
| --- | --- |
| `grpc_service_call` | 14 |
| `http_service_call` | 3 |
| `cache_client_usage` | 1 |
| `database_client_usage` | 0 |

Every resolved source finding corresponds to a documented Online Boutique
application relationship and carries the matching dependency-resolution
relationship id:

- `frontend -> adservice`, `cartservice`, `checkoutservice`, `currencyservice`,
  `productcatalogservice`, `recommendationservice`, `shippingservice`
  (gRPC call sites)
- `frontend -> shoppingassistantservice` (HTTP call resolved through
  `SHOPPING_ASSISTANT_SERVICE_ADDR`)
- `checkoutservice -> cartservice`, `currencyservice`, `emailservice`,
  `paymentservice`, `productcatalogservice`, `shippingservice` (gRPC call sites)
- `recommendationservice -> productcatalogservice` (Python gRPC stub)
- `loadgenerator -> frontend` (Locust HTTP calls, resolved through the
  component's only configured endpoint)
- `cartservice -> redis-cart` (C# distributed-cache construction and operations)

## Evidence breakdown

| Evidence type | Count |
| --- | --- |
| `grpc_client_construction` | 20 |
| `grpc_client_invocation` | 20 |
| `http_client_invocation` | 11 |
| `cache_client_construction` | 1 |
| `cache_client_invocation` | 4 |

Languages analysed: Go 16 files, C# 8, Python 6, JavaScript 5, Java 2.

## False dependencies avoided

- Generated code was skipped (`*.pb.go`, `*_pb2_grpc.py`, generated C# and Node
  files): 12 files.
- Standalone client/example files were skipped, including
  `recommendationservice/client.py` and `currencyservice/client.js`: 3 files.
- The Java `adservice` self-reference was ignored, so no self-edge was produced.
- An import of generated packages produced no finding.
- C# `IDistributedCache.GetAsync` was classified as a cache operation, not an
  HTTP call.
- Shared Protobuf messages and generated contracts produced no edges.
- Multiple call sites were aggregated: `loadgenerator -> frontend` is one
  finding with 9 HTTP call-site evidence entries.

## Unresolved finding

`frontend -> env:PACKAGING_SERVICE_URL` is preserved as unresolved. The Go code
performs `http.Get(url)` with a URL assembled from the
`PACKAGING_SERVICE_URL` environment variable, but dependency resolution has no
component for that target. The finding keeps the configuration key, file, line
and HTTP method rather than inventing a component.

## Limitations

- Static analysis shows that a call path exists in source; it does not prove the
  path executes at runtime.
- The analyzer is scoped to the languages and client patterns present in Online
  Boutique. Unsupported languages are counted and diagnosed.
- Optional database clients are not reported unless the pattern is recognised
  and dependency resolution already identified a matching infrastructure target.
  The optional AlloyDB path in `productcatalogservice` is therefore not in the
  graph.
- HTTP targets need a literal host, a configured environment key already mapped
  by dependency resolution, or the component's only configured endpoint.
- Generated code is skipped deliberately. Calls made inside generated clients
  are represented by the business-code call site that invokes them.
- This stage writes evidence only. It does not write to Neo4j and does not claim
  that the source graph replaces runtime or manifest evidence.
