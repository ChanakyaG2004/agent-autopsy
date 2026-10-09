"""Local Phoenix launcher with its unused gRPC listener disabled.

Phoenix 20.23 binds gRPC to all interfaces; --grpc-port 0 chooses a random port.
Keep this compatibility adapter here, without editing installed package files.
"""

import phoenix.server.app as phoenix_app
from phoenix.server.grpc_server import GrpcServer
from phoenix.server.main import main


class HTTPOnlyGrpcServer(GrpcServer):
    def __init__(self, *args, **kwargs):
        kwargs["disabled"] = True
        super().__init__(*args, **kwargs)


if __name__ == "__main__":
    phoenix_app.GrpcServer = HTTPOnlyGrpcServer
    main()
