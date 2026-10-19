package main

import (
	"context"

	pb "example/genproto"
)

func placeOrder(conn interface{}) {
	_, _ = pb.NewCheckoutServiceClient(conn).PlaceOrder(context.Background(), &pb.Order{})
}
