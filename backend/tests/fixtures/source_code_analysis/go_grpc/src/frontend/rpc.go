package main

import (
	"context"

	pb "example/genproto"
)

func listProducts(conn interface{}) {
	_, _ = pb.NewProductCatalogServiceClient(conn).ListProducts(context.Background(), &pb.Empty{})
}

func getCart(conn interface{}) {
	client := pb.NewCartServiceClient(conn)
	_, _ = client.GetCart(context.Background(), &pb.GetCartRequest{})
}

func getMissing(conn interface{}) {
	_, _ = pb.NewMissingServiceClient(conn).DoThing(context.Background(), &pb.Empty{})
}
