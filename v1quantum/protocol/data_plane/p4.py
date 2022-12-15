"""The P4 program loader. It's constructed as a protocol to work with NetSquid NetRunner."""

from netsquid.protocols import NodeProtocol


class P4DataPlane(NodeProtocol):

    def __init__(self, node, config, program_file_name=None):
        super().__init__(node, f"{node.name}-p4-data-plane")
        node.p4device.load(program_file_name)

    def run(self):
        # The data plane runs as a set of protocols on the p4device.
        pass
