"""
gRPC service implementation
Shows cross-language protocol usage
"""

from concurrent import futures

import grpc
import protobuf  # Cross-language dependency

# Local imports to test resolution
from .models import DataModel, User
from .utils import validate_request


class DataService:
    def GetData(self, request, context):
        # Validate using local utility
        if not validate_request(request):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            return None

        # Return protobuf message
        return DataModel(id=request.id, value="test")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    # Add service implementation
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()
