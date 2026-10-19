# Dependency resolution: Online Boutique validation

Validated on the Google Online Boutique working tree at commit
`38e7348eb289eb5b87c0c6e8cb19ced0449dc389`, through the real pipeline:
repository inventory -> manifest analysis -> component discovery -> dependency
resolution. No expected relationship was hardcoded in the resolver.

## Pipeline input

| Stage | Result |
| --- | --- |
| Repository inventory | 357 files, 20 candidate components, not truncated |
| Manifest analysis | 78 files, 360 resources, 359 relationships, 52 endpoints, 0 failed files |
| Component discovery | 13 components, 102 artifacts, 5 unresolved artifacts |
| Dependency resolution | 17 resolved relationships |

## Resolved relationships

| Type | Count |
| --- | --- |
| `configured_endpoint` | 16 |
| `infrastructure_dependency` | 1 |
| `declared_dependency` | 0 |
| `resource_selection` | 0 |

The single infrastructure relationship is `cartservice -> redis-cart`, classified
as `cache` from the `redis:alpine` container image.

Configured application relationships recovered:

- `frontend -> adservice`
- `frontend -> cartservice`
- `frontend -> checkoutservice`
- `frontend -> currencyservice`
- `frontend -> productcatalogservice`
- `frontend -> recommendationservice`
- `frontend -> shippingservice`
- `frontend -> shoppingassistantservice`
- `checkoutservice -> cartservice`
- `checkoutservice -> currencyservice`
- `checkoutservice -> emailservice`
- `checkoutservice -> paymentservice`
- `checkoutservice -> productcatalogservice`
- `checkoutservice -> shippingservice`
- `recommendationservice -> productcatalogservice`
- `loadgenerator -> frontend`

These match the documented Online Boutique call graph.

## Evidence and diagnostics

| Metric | Value |
| --- | --- |
| Evidence entries | 94 |
| Evidence by source | `component_discovery` 75, `manifest_analysis` 19 |
| Unresolved candidates | 0 |
| Ambiguous candidates | 0 |
| Duplicate evidence aggregated | 1 |
| Diagnostics | 0 |

- 18 environment-configured endpoints produced 17 relationships. The
  `loadgenerator -> frontend` reference appears in two manifests and was
  aggregated into one logical relationship.
- 12 Kubernetes Service selectors were inspected. Every selector targeted a
  workload of the same component, so none became a cross-component edge.
- No Compose `depends_on` declarations exist in this repository, so no
  `declared_dependency` edges were expected.
- `frontend -> shoppingassistantservice` is reported as `inferred` because the
  component has no deployment artifact alias in the analysed manifests. The
  endpoint itself is explicitly declared (`SHOPPING_ASSISTANT_SERVICE_ADDR`).
- The five unresolved component-discovery artifacts are protobuf `Health`
  services and directory groups; none of them is a network endpoint.

## Limitations

The graph is not complete, and its completeness cannot be inferred from the
result count.

- Source-code evidence (SCIP or AST analysis) is not integrated. A call that has
  no configured address and no deployment declaration is not discovered. In this
  revision of Online Boutique every documented application-level relationship is
  also present in an environment address, so the configured-endpoint evidence
  recovers the documented call graph; the undiscovered class remains any
  source-code-only call with no address configuration.
- API and protobuf contracts are supporting evidence only. A contract does not
  prove that a component calls it, so shared messages never create edges.
- Kubernetes ConfigMap values are recorded by key only (`values_extracted` is
  false). Endpoints configured exclusively through `envFrom` or a ConfigMap value
  are therefore not resolved yet. ConfigMap, Secret and volume references remain
  configuration of their own component rather than becoming component edges.
- Infrastructure classification depends on recognised container image families.
  An unrecognised data-store image remains an application component.
- The resolver distinguishes configured endpoints, declared startup dependencies,
  infrastructure connections and resource selection. None of them is verified
  runtime communication.
