package main

import (
	"context"

	pb "example/genproto"
)

func charge(conn interface{}) {
	_, _ = pb.NewPaymentServiceClient(conn).Charge(context.Background(), &pb.ChargeRequest{})
}

func missing(conn interface{}) {
	_, _ = pb.NewMissingServiceClient(conn).DoThing(context.Background(), &pb.Empty{})
}
