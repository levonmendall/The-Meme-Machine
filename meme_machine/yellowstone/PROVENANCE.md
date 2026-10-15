Protocol schemas from rpcpool/yellowstone-grpc commit fb1aaf67cb8b50802d8b59b58a1ac4b274f4acc4, package yellowstone-grpc-proto 14.0.1 (Apache-2.0).

Schema SHA256:
- geyser.proto: 80ee337f361198a0722cb5bdf244fe41838949ab7a3af6d1b182b7fdca9abf02
- solana-storage.proto: e5d16ba9a9e83f6ed8c92a96b6b75dfd64c43f897b976011eb3ec5abe2f3c818

Generated using grpcio-tools 1.84.0 (protobuf generator 7.35.1):

    python -m grpc_tools.protoc -I meme_machine/yellowstone --python_out=meme_machine/yellowstone meme_machine/yellowstone/geyser.proto meme_machine/yellowstone/solana-storage.proto

The generated geyser binding uses a package-relative solana_storage_pb2 import.
Both generated `BuildTopDescriptorsAndMessages` module names are qualified with
`meme_machine.yellowstone.` so the existing spawned decoder processes can pickle
the protocol messages. These changes do not change the descriptors or wire bytes.
No signing, submission, or execution RPC is exposed by the application adapter.
