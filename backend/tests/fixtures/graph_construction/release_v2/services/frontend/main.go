package main

import (
	"context"

	pb "example/genproto"
)

func placeOrder(conn interface{}) {
	_, _ = pb.NewCheckoutServiceClient(conn).PlaceOrder(context.Background(), &pb.Order{})
}

func addToCart(conn interface{}) {
	_, _ = pb.NewCartServiceClient(conn).AddItem(context.Background(), &pb.CartItem{})
}
