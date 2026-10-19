package main

import "net/http"

func callUnknownService() {
	_, _ = http.Get("http://unknown.example:8080/health")
}
