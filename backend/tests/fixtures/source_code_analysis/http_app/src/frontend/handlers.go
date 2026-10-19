package main

import "net/http"

func (fe *frontendServer) assistantHandler(r *http.Request) {
	url := "http://" + fe.shoppingAssistantSvcAddr
	req, _ := http.NewRequest(http.MethodPost, url, r.Body)
	_, _ = http.DefaultClient.Do(req)

	// Constructing a client is not a call and must not create a finding.
	_ = &http.Client{}
}
