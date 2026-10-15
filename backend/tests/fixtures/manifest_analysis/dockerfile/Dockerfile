# syntax=docker/dockerfile:1
FROM golang:1.22 AS build
ARG BUILD_VERSION=dev
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/cart -ldflags="-X main.version=${BUILD_VERSION}" .

FROM alpine:3.20 AS runtime
RUN apk add --no-cache ca-certificates
COPY --from=build /out/cart /usr/local/bin/cart
COPY --from=missing-stage /nope /nope
COPY config/app.yaml /etc/app.yaml
ENV LOG_LEVEL=info \
    DB_PASSWORD=hunter2 \
    REGISTRY_URL=https://registry.example.com
EXPOSE 8080
EXPOSE 9090/udp
USER nobody
ENTRYPOINT ["/usr/local/bin/cart"]
CMD ["--serve"]
HEALTHCHECK CMD wget -q -O- http://localhost:8080/health || exit 1
