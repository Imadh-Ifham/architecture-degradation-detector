"""Build the subject working trees the validation fixtures are recorded from.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Writes two thin working trees under `subject/`, one per release of the
    subject system, with the real service names, manifest paths and container
    environment values taken from the upstream repository at those tags.

    The trees are **generated, not committed**. They are roughly a hundred
    files of scaffolding whose only job is to be walked, and committing them
    would bury seventy files of real work in review. `subject/` is ignored, and
    a session fixture in conftest.py regenerates it when it is missing.

    What *is* committed is this script and the two recorded inventories. That
    keeps the recording reproducible - the point of the recording is that when
    the recovery component changes, re-running it produces a reviewable diff -
    while keeping the repository readable.

    Run it directly, or let the test suite do it:

        python tests/fixtures/validation/build_subject_tree.py
"""

import os
import shutil

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subject")

# service -> declared dependencies as (ENV_NAME, host:port), from the real manifests
SERVICES = {
    "frontend": [
        ("PRODUCT_CATALOG_SERVICE_ADDR", "productcatalogservice:3550"),
        ("CURRENCY_SERVICE_ADDR", "currencyservice:7000"),
        ("CART_SERVICE_ADDR", "cartservice:7070"),
        ("RECOMMENDATION_SERVICE_ADDR", "recommendationservice:8080"),
        ("SHIPPING_SERVICE_ADDR", "shippingservice:50051"),
        ("CHECKOUT_SERVICE_ADDR", "checkoutservice:5050"),
        ("AD_SERVICE_ADDR", "adservice:9555"),
    ],
    "checkoutservice": [
        ("PRODUCT_CATALOG_SERVICE_ADDR", "productcatalogservice:3550"),
        ("SHIPPING_SERVICE_ADDR", "shippingservice:50051"),
        ("PAYMENT_SERVICE_ADDR", "paymentservice:50051"),
        ("EMAIL_SERVICE_ADDR", "emailservice:5000"),
        ("CURRENCY_SERVICE_ADDR", "currencyservice:7000"),
        ("CART_SERVICE_ADDR", "cartservice:7070"),
    ],
    "recommendationservice": [
        ("PRODUCT_CATALOG_SERVICE_ADDR", "productcatalogservice:3550"),
    ],
    "cartservice": [("REDIS_ADDR", "redis-cart:6379")],
    "productcatalogservice": [],
    "shippingservice": [],
    "paymentservice": [],
    "emailservice": [],
    "currencyservice": [],
    "adservice": [],
    "loadgenerator": [("FRONTEND_ADDR", "frontend:80")],
}

PORTS = {
    "frontend": 8080,
    "checkoutservice": 5050,
    "recommendationservice": 8080,
    "cartservice": 7070,
    "productcatalogservice": 3550,
    "shippingservice": 50051,
    "paymentservice": 50051,
    "emailservice": 8080,
    "currencyservice": 7000,
    "adservice": 9555,
    "loadgenerator": 8080,
}

LANGUAGES = {
    "frontend": ("go", "main.go", "go.mod"),
    "checkoutservice": ("go", "main.go", "go.mod"),
    "productcatalogservice": ("go", "main.go", "go.mod"),
    "shippingservice": ("go", "main.go", "go.mod"),
    "cartservice": ("csharp", "Program.cs", "cartservice.csproj"),
    "currencyservice": ("node", "server.js", "package.json"),
    "paymentservice": ("node", "index.js", "package.json"),
    "emailservice": ("python", "email_server.py", "requirements.txt"),
    "recommendationservice": ("python", "recommendation_server.py", "requirements.txt"),
    "loadgenerator": ("python", "locustfile.py", "requirements.txt"),
    "adservice": ("java", "src/main/java/Ads.java", "build.gradle"),
}

BUILD_MANIFEST = {
    "go.mod": "module github.com/GoogleCloudPlatform/microservices-demo/src/{name}\n\ngo 1.22\n",
    "package.json": '{{\n  "name": "{name}",\n  "version": "0.1.0",\n  "main": "index.js"\n}}\n',
    "requirements.txt": "grpcio==1.62.0\nopentelemetry-sdk==1.23.0\n",
    "cartservice.csproj": (
        '<Project Sdk="Microsoft.NET.Sdk.Web">\n'
        "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
        "</Project>\n"
    ),
    "build.gradle": "plugins {{ id 'java' }}\nrepositories {{ mavenCentral() }}\n",
}


def deployment(name, dependencies, port):
    env = [f'            - name: PORT\n              value: "{port}"']
    for key, value in dependencies:
        env.append(f'            - name: {key}\n              value: "{value}"')
    env_block = "\n".join(env)
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
spec:
  selector:
    matchLabels:
      app: {name}
  template:
    metadata:
      labels:
        app: {name}
    spec:
      serviceAccountName: {name}
      containers:
        - name: server
          image: {name}
          ports:
            - containerPort: {port}
          env:
{env_block}
          resources:
            requests:
              cpu: 100m
              memory: 64Mi
---
apiVersion: v1
kind: Service
metadata:
  name: {name}
spec:
  type: ClusterIP
  selector:
    app: {name}
  ports:
    - name: grpc
      port: {port}
      targetPort: {port}
"""


def network_policy(name, ingress_from):
    peers = "\n".join(
        f"        - podSelector:\n            matchLabels:\n              app: {peer}"
        for peer in ingress_from
    ) or "        []"
    return f"""apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {name}
spec:
  podSelector:
    matchLabels:
      app: {name}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
{peers}
"""


DENY_ALL = """apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
"""

SHOPPING_ASSISTANT = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: shoppingassistantservice
spec:
  selector:
    matchLabels:
      app: shoppingassistantservice
  template:
    metadata:
      labels:
        app: shoppingassistantservice
    spec:
      serviceAccountName: shoppingassistantservice
      containers:
        - name: server
          image: shoppingassistantservice
          ports:
            - containerPort: 8080
          env:
            - name: PORT
              value: "8080"
            - name: ALLOYDB_CLUSTER_NAME
              value: "ALLOYDB_CLUSTER_NAME_VAL"
            - name: ALLOYDB_DATABASE_NAME
              value: "ALLOYDB_DATABASE_NAME_VAL"
            - name: PROJECT_ID
              value: "PROJECT_ID_VAL"
---
apiVersion: v1
kind: Service
metadata:
  name: shoppingassistantservice
spec:
  type: ClusterIP
  selector:
    app: shoppingassistantservice
  ports:
    - name: http
      port: 80
      targetPort: 8080
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: shoppingassistantservice
  annotations:
    iam.gke.io/gcp-service-account: ALLOYDB_USER_GSA_ID
"""

SERVICE_ACCOUNT = """apiVersion: v1
kind: ServiceAccount
metadata:
  name: {name}
  annotations:
    iam.gke.io/gcp-service-account: {name}@PROJECT_ID.iam.gserviceaccount.com
"""

PROTO = """syntax = "proto3";
package hipstershop;

service CartService {
  rpc AddItem(AddItemRequest) returns (Empty) {}
  rpc GetCart(GetCartRequest) returns (Cart) {}
  rpc EmptyCart(EmptyCartRequest) returns (Empty) {}
}

service PaymentService {
  rpc Charge(ChargeRequest) returns (ChargeResponse) {}
}

service ShippingService {
  rpc GetQuote(GetQuoteRequest) returns (GetQuoteResponse) {}
  rpc ShipOrder(ShipOrderRequest) returns (ShipOrderResponse) {}
}

service CheckoutService {
  rpc PlaceOrder(PlaceOrderRequest) returns (PlaceOrderResponse) {}
}

message Empty {}
"""

# Which services each policy admits ingress from, mirroring the real set.
INGRESS = {
    "frontend": ["loadgenerator"],
    "checkoutservice": ["frontend"],
    "cartservice": ["frontend", "checkoutservice"],
    "productcatalogservice": ["frontend", "checkoutservice", "recommendationservice"],
    "currencyservice": ["frontend", "checkoutservice"],
    "paymentservice": ["checkoutservice"],
    "shippingservice": ["frontend", "checkoutservice"],
    "emailservice": ["checkoutservice"],
    "recommendationservice": ["frontend"],
    "adservice": ["frontend"],
    "redis": ["cartservice"],
    "loadgenerator": [],
}


COMMENT_TOKEN = {"python": "#"}
"""Comment token per language, defaulting to `//`.

The file bodies are placeholders - the inventory counts and classifies
files without reading them - but a generated `.py` holding a `//` comment
is not valid Python, and anything that walks the tree with a parser trips
over it.
"""


def write(path, text):
    full = os.path.join(BASE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def build(release, include_shopping_assistant, include_service_accounts):
    prefix = release
    for name, dependencies in SERVICES.items():
        write(
            f"{prefix}/kustomize/base/{name}.yaml",
            deployment(name, dependencies, PORTS[name]),
        )
        language, source, manifest = LANGUAGES[name]
        token = COMMENT_TOKEN.get(language, "//")
        write(f"{prefix}/src/{name}/{source}", f"{token} {name} ({language})\n")
        write(
            f"{prefix}/src/{name}/{manifest}",
            BUILD_MANIFEST[manifest].format(name=name),
        )

    write(
        f"{prefix}/kustomize/base/kustomization.yaml",
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        + "".join(f"  - {name}.yaml\n" for name in sorted(SERVICES)),
    )

    write(f"{prefix}/kustomize/components/network-policies/network-policy-deny-all.yaml", DENY_ALL)
    for name, peers in INGRESS.items():
        write(
            f"{prefix}/kustomize/components/network-policies/network-policy-{name}.yaml",
            network_policy(name, peers),
        )
    write(
        f"{prefix}/kustomize/components/network-policies/kustomization.yaml",
        "apiVersion: kustomize.config.k8s.io/v1alpha1\nkind: Component\nresources:\n"
        "  - network-policy-deny-all.yaml\n"
        + "".join(f"  - network-policy-{name}.yaml\n" for name in sorted(INGRESS)),
    )

    if include_service_accounts:
        for name in sorted(SERVICES):
            write(
                f"{prefix}/kustomize/components/service-accounts/service-account-{name}.yaml",
                SERVICE_ACCOUNT.format(name=name),
            )
        write(
            f"{prefix}/kustomize/components/service-accounts/kustomization.yaml",
            "apiVersion: kustomize.config.k8s.io/v1alpha1\nkind: Component\nresources:\n"
            + "".join(f"  - service-account-{name}.yaml\n" for name in sorted(SERVICES)),
        )

    if include_shopping_assistant:
        write(
            f"{prefix}/kustomize/components/shopping-assistant/shoppingassistantservice.yaml",
            SHOPPING_ASSISTANT,
        )
        write(
            f"{prefix}/kustomize/components/shopping-assistant/kustomization.yaml",
            "apiVersion: kustomize.config.k8s.io/v1alpha1\nkind: Component\nresources:\n"
            "  - shoppingassistantservice.yaml\n",
        )
        write(f"{prefix}/src/shoppingassistantservice/main.py", "# shoppingassistantservice\n")
        write(f"{prefix}/src/shoppingassistantservice/requirements.txt", "langchain==0.1.0\n")

    write(f"{prefix}/protos/demo.proto", PROTO)
    write(
        f"{prefix}/README.md",
        f"# Online Boutique\n\nA cloud-first microservices demo application.\n\nRelease {release}.\n",
    )


def build_all(force: bool = False) -> str:
    """Write both trees and return the root they were written to."""

    if os.path.isdir(BASE):
        if not force:
            return BASE
        shutil.rmtree(BASE)

    build("v0.9.0", include_shopping_assistant=False, include_service_accounts=True)
    build("v0.10.0", include_shopping_assistant=True, include_service_accounts=False)
    return BASE


if __name__ == "__main__":
    build_all(force=True)
    for release in ("v0.9.0", "v0.10.0"):
        count = sum(len(files) for _, _, files in os.walk(os.path.join(BASE, release)))
        print(release, count, "files")
