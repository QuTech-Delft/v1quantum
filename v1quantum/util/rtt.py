"""An RTT estimation protocol."""

from dataclasses import dataclass
from typing import Optional

from netsquid.protocols import NodeProtocol
import netsquid as ns


class RttProtocol(NodeProtocol):
    """An RTT estimation protocol.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The NetSquid node object on which this protocol will run.
    port : `~netsquid.components.component.Port`
        The port on which to run this protocol.

    """

    @dataclass
    class Message:
        """The RTT ping message."""
        src: str
        dst: Optional[str] = None

    def __init__(self, node, port):
        super().__init__(node)
        self.__port = port

    def run(self):
        """Run the RTT estimation protocol."""
        response = None
        while response is None:
            send_time = ns.sim_time()
            message = RttProtocol.Message(src=self.node.name)
            self.__port.tx_output(message)

            yield self.await_port_input(self.__port) | self.await_timer(ns.SECOND)
            response = self.__port.rx_input()

            if response is None:
                continue

            assert len(response.items) == 1
            item = response.items[0]
            assert item is message
            assert item.dst is not None

            recv_time = ns.sim_time()
            rtt = recv_time - send_time
            return rtt
