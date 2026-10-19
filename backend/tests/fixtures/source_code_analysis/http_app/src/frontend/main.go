package main

import "os"

type frontendServer struct {
	shoppingAssistantSvcAddr string
}

func mustMapEnv(target *string, key string) {
	*target = os.Getenv(key)
}

func main() {
	var svc frontendServer
	mustMapEnv(&svc.shoppingAssistantSvcAddr, "SHOPPING_ASSISTANT_SERVICE_ADDR")
	_ = svc
}
