class Shopper:
    def browse(self) -> None:
        self.client.get("/")
        self.client.post("/cart", {"product_id": "1"})
