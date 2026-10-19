package main

import (
	pb "example/genproto"
)

// Keeping a generated package imported is not evidence that the service calls
// any client it contains.
var _ = pb.Empty{}
