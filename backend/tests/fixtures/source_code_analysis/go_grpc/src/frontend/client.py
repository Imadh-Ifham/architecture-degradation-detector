import grpc

from example import demo_pb2_grpc


def main() -> None:
    channel = grpc.insecure_channel("localhost:8080")
    stub = demo_pb2_grpc.RecommendationServiceStub(channel)
    stub.ListRecommendations(None)
