"""The host protocol."""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from functools import reduce
import logging
from typing import Optional

from netsquid_netrunner.demand.application import Application as NetworkApp
from netsquid.protocols import NodeProtocol
import netsquid as ns
from pydynaa import EventType

from v1quantum.protocol.control_plane.agent import Agent
from v1quantum.protocol.control_plane.protocol import QcpMsg, QcpOp, RequestMsg
from v1quantum.processor import V1QuantumBellIndex


CTL_PORT = 0x200


logger = logging.getLogger(__name__)


class Signals(Enum):
    """Signals used by the Entangle and Measure protocol and its subprotocols."""
    CTL_RSRV_MSG = EventType("CTL_RSRV_MSG", "RSRV message from controller")
    CTL_FREE_MSG = EventType("CTL_FREE_MSG", "FREE message from controller")
    CTL_RULE_MSG = EventType("CTL_RULE_MSG", "RULE message from controller")
    ENTMSR_START = EventType("ENTMSR_START", "Entangle and measure")
    ENTMSR_COMPL = EventType("ENTMSR_COMPL", "Entangle and measure complete")


class EntangleAndMeasure(NodeProtocol):
    """Application that generates entangled pairs and measures them.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The node running this protocol.

    """

    @dataclass
    class RequestData:
        request: NetworkApp
        results: 'EntangleAndMeasure.RequestResults'

    @dataclass
    class RequestResults:
        """Internal request state."""
        request_time: float
        start_time: Optional[float] = None
        end_time: Optional[float] = None
        outcomes: Optional[list] = None

    def __init__(self, node, network_config):
        # pylint: disable=unused-argument
        super().__init__(node)
        self.__host = self.node.name

        self.add_subprotocol(EntangleAndMeasure.HostPortSubProtocol(node, self), "HOSTPORT")
        self.add_subprotocol(EntangleAndMeasure.CtlPortSubProtocol(node), "CTLPORT")
        self.add_subprotocol(EntangleAndMeasure.AgentSubProtocol(node, self), "AGENT")
        self.add_subprotocol(EntangleAndMeasure.EntMsrSubProtocol(node, self), "ENTMSR")

        for signal in Signals:
            self.add_signal(signal)

        self.__current_request_id = None
        self.__current_remote_id = None
        self.__requests = {}
        self.__results = {}

    def print_status(self):
        """Print the current status of this protocol."""
        if self.current_request_id is None:
            print(f"{self.node.name} :: IDLE")
        else:
            print(f"{self.node.name} :: req{self.node.protocol.current_request_id} -- "
                  f"{self.node.name}-{self.node.protocol.current_remote_id} : "
                  f"{self.node.protocol.complete_pairs}/{self.node.protocol.num_pairs}")

    @staticmethod
    def print_results(app0_results, app1_results):
        """Print the final results from both hosts.

        Parameters
        ----------
        app0_results : `protocol.control_plane.host.EntangleAndMeasure.RequestData`
            Results from one of the hosts.
        app1_results : `protocol.control_plane.host.EntangleAndMeasure.RequestData`
            Results from the other host.

        """
        app0_outcomes = app0_results.outcomes
        app1_outcomes = app1_results.outcomes
        assert len(app0_outcomes) == len(app1_outcomes)

        qber = 0
        for app0_out, app1_out in zip(app0_outcomes, app1_outcomes):
            app0_bell_index, app0_outcome = app0_out
            app1_bell_index, app1_outcome = app1_out
            assert app0_bell_index == app1_bell_index

            if app0_bell_index in (V1QuantumBellIndex.PSI_PLUS, V1QuantumBellIndex.PSI_MINS):
                app0_outcome = app0_outcome ^ 1

            qber += int(app0_outcome != app1_outcome)

        qber /= len(app0_outcomes)

        print(f"request_time : {int(app0_results.request_time) / ns.SECOND}")
        print(f"start_time   : {int(app0_results.start_time) / ns.SECOND}")
        print(f"end_time     : {int(app0_results.end_time) / ns.SECOND}")
        print(f"QBER : {qber}")

    @property
    def host(self):
        """`str`: The name of this host."""
        return self.__host

    @property
    def current_request_id(self):
        """`Optional[int]`: The ID for the current request."""
        return self.__current_request_id

    @property
    def current_remote_id(self):
        """`Optional[int]`: The remote for the current request."""
        return self.__current_remote_id

    @property
    def complete_pairs(self):
        """`Optional[int]`: The number of pairs completed in the current request."""
        return self.subprotocols["ENTMSR"].complete_pairs

    @property
    def num_pairs(self):
        """`Optional[int]`: The total number of pairs in the current request."""
        return self.subprotocols["ENTMSR"].num_pairs

    def request(self, new_request):
        """Issue a new request to the protocol.

        Parameters
        ----------
        new_request : `qp4_simulations.host.app.Request`
            The issued request.

        """
        self.node.ports[new_request.host1].tx_output(deepcopy(new_request))
        self.enqueue_request(new_request)

    def enqueue_request(self, request):
        """Enqueue the new request locally.


        Parameters
        ----------
        request : `~netsquid_netrunner.loader.network.NetworkApp`.
            The request.

        """
        self.__requests[request.request_id] = EntangleAndMeasure.RequestData(
            request=request,
            results=EntangleAndMeasure.RequestResults(request_time=ns.sim_time()),
        )
        self.reserve(request)

    def reserve(self, request):
        """Send a RSRV message to the controller for the provided request.

        Parameters
        ----------
        request : `~netsquid_netrunner.loader.network.NetworkApp`.
            The request.

        """
        self.ctlmsg(QcpOp.OP_RSRV, request)

    def release(self, request):
        """Send a FREE message to the controller for the provided request.

        Parameters
        ----------
        request : `~netsquid_netrunner.loader.network.NetworkApp`.
            The request.

        """
        self.ctlmsg(QcpOp.OP_FREE, request)

    def ctlmsg(self, msg_type, request):
        """Send a MSG_TYPE message to the controller for the provided request.

        Parameters
        ----------
        msg_type : `v1quantum.protocol.protocol.QcpOp`
            The message type.
        request : `~netsquid_netrunner.loader.network.NetworkApp`.
            The request.

        """
        assert self.host == request.host0
        msg = RequestMsg(
            msg_type=msg_type,
            source=request.host0,
            remote=request.host1,
            request_id=request.request_id,
        )
        self.node.ports[str(CTL_PORT)].tx_output(msg)

    def results(self, request_id):
        """Get the results for a particular request.

        Parameters
        ----------
        request_id : `int`
            The request ID for which the results are to be returned.

        Returns
        -------
        `Dict`
            The results dictionary.

        """
        return self.__results.get(request_id, None)

    def run(self):
        """Run the Entangle and Measure protocol."""
        self.start_subprotocols()

        while True:
            yield self.await_signal(self.subprotocols["CTLPORT"], Signals.CTL_RSRV_MSG)
            reserve = self.subprotocols["CTLPORT"].get_signal_result(Signals.CTL_RSRV_MSG, self)

            assert reserve.request_id not in self.__results
            assert reserve.source == self.host

            request_data = self.__requests[reserve.request_id]
            request = request_data.request

            assert reserve.source == request.host0
            assert reserve.remote == request.host1

            self.__current_request_id = request.request_id
            self.__current_remote_id = request.host1

            # Start time is the moment we start entangling.
            request_data.results.start_time = ns.sim_time()

            # Entangle and measure
            entmsr_params = EntangleAndMeasure.EntMsrSubProtocol.Params(
                request_id=request.request_id,
                remote_id=request.host1,
                num_pairs=request.parameters["num_pairs"],
            )
            self.send_signal(Signals.ENTMSR_START, result=entmsr_params)
            yield self.await_signal(self.subprotocols["ENTMSR"], Signals.ENTMSR_COMPL)
            request_data.results.outcomes = \
                self.subprotocols["ENTMSR"].get_signal_result(Signals.ENTMSR_COMPL, self)

            # End time is the moment entanglement completes.
            request_data.results.end_time = ns.sim_time()

            # The results are ready.
            self.__results[request.request_id] = request_data.results

            # Send a release now.
            self.release(request)

            yield self.await_signal(self.subprotocols["CTLPORT"], Signals.CTL_FREE_MSG)
            release = self.subprotocols["CTLPORT"].get_signal_result(Signals.CTL_FREE_MSG, self)

            assert release.request_id == request.request_id
            assert release.source == self.host
            assert release.source == request.host0
            assert release.remote == request.host1

            del self.__requests[release.request_id]

            # Reset current request ID
            self.__current_request_id = None
            self.__current_remote_id = None

    class HostPortSubProtocol(NodeProtocol):
        """The inter-host subprotocol.

        This subprotocol listens on the ports leading to the other hosts.

        Parameters
        ----------
        node : `~netsquid.nodes.Node`
            The node running this subprotocol.
        parent : `~netsquid.protocols.NodeProtocol`
            The parent protocol.

        """

        def __init__(self, node, parent):
            super().__init__(node)
            self.__parent = parent

        def __host_ports(self):
            return filter(
                lambda p: not (p.name.isdigit() or
                               p.name.startswith("cl-") or
                               p.name.startswith("qu")),
                self.node.ports.values(),
            )

        def __await_host_port_input(self):
            return reduce(
                lambda a, b: a | b,
                [self.await_port_input(p) for p in self.__host_ports()],
            )

        def run(self):
            """Run the subprotocol."""
            while True:
                yield self.__await_host_port_input()

                for port in self.__host_ports():
                    msg = port.rx_input()

                    # Because we must loop through all the ports to figure out which one triggered
                    # the event, some of them will return None.
                    if msg is None:
                        continue

                    assert msg.items is not None
                    for request in msg.items:
                        assert request.host1 == self.__parent.host
                        request.host0, request.host1 = request.host1, request.host0
                        self.__parent.enqueue_request(request)

    class CtlPortSubProtocol(NodeProtocol):
        """The Controller Port subprotocol.

        The Controller Port subprotocol listens on the controller port and passes received messages
        to correct handler.

        Parameters
        ----------
        node : `~netsquid.nodes.Node`
            The node running this subprotocol.

        """

        def __init__(self, node):
            super().__init__(node)

            self.add_signal(Signals.CTL_RSRV_MSG)
            self.add_signal(Signals.CTL_FREE_MSG)
            self.add_signal(Signals.CTL_RULE_MSG)

        def run(self):
            """Run the Controller Port subprotocol."""
            port = self.node.ports[str(CTL_PORT)]

            while True:
                yield self.await_port_input(port)
                msg = port.rx_input()
                assert msg is not None
                assert msg.items is not None

                rsrv_items = []
                free_items = []
                rule_items = []

                for message in msg.items:
                    message: QcpMsg
                    if message.msg_type == QcpOp.OP_RSRV:
                        rsrv_items.append(message)
                    elif message.msg_type == QcpOp.OP_FREE:
                        free_items.append(message)
                    else:
                        assert message.msg_type == QcpOp.OP_RULE
                        rule_items.append(message)

                if rsrv_items:
                    assert len(rsrv_items) == 1
                    assert not free_items
                    self.send_signal(Signals.CTL_RSRV_MSG, result=rsrv_items[0])
                if free_items:
                    assert not rsrv_items
                    assert len(free_items) == 1
                    self.send_signal(Signals.CTL_FREE_MSG, result=free_items[0])
                if rule_items:
                    self.send_signal(Signals.CTL_RULE_MSG, result=rule_items)

    class AgentSubProtocol(Agent):
        """The Agent subprotocol.

        Parameters
        ----------
        node : `~netsquid.nodes.Node`
            The node running this subprotocol.
        parent : `~netsquid.protocols.NodeProtocol`
            The parent protocol.

        """

        def __init__(self, node, parent):
            super().__init__(node, {})
            self.__parent = parent

            self.add_signal(Signals.CTL_RULE_MSG)

        def run(self):
            """Run the Agent subprotocol."""
            while True:
                ctlport = self.__parent.subprotocols["CTLPORT"]
                yield self.await_signal(ctlport, Signals.CTL_RULE_MSG)
                items = ctlport.get_signal_result(Signals.CTL_RULE_MSG, self)

                assert items is not None
                self._process(items)

    class EntMsrSubProtocol(NodeProtocol):
        """The Entangle and Measure subprotocol.

        Parameters
        ----------
        node : `~netsquid.nodes.Node`
            The node running this subprotocol.
        parent : `~netsquid.protocols.NodeProtocol`
            The parent protocol.

        """

        @dataclass
        class Params:
            """Parameters for the Entangle and Measure subprotocol."""
            request_id: int
            remote_id: int
            num_pairs: int

        def __init__(self, node, parent):
            super().__init__(node)

            self.__parent = parent
            self.__complete_pairs = None
            self.__num_pairs = None

            self.add_signal(Signals.ENTMSR_START)
            self.add_signal(Signals.ENTMSR_COMPL)

        @property
        def complete_pairs(self):
            """`Optional[int]`: The number of pairs completed in the current request."""
            return self.__complete_pairs

        @property
        def num_pairs(self):
            """`Optional[int]`: The total number of pairs in the current request."""
            return self.__num_pairs

        def run(self):
            """Run the Entangle and Measure subprotocol."""
            while True:
                # Always monitor port 0 to discard qubits that nobody is waiting for.
                yield (self.await_signal(self.__parent, Signals.ENTMSR_START) |
                       self.await_port_output(self.node.ports["0"]))

                if self.node.ports["0"].rx_output() is not None:
                    # Then we must have received an unexpected qubit.
                    self.node.qubit_discard(1)
                    continue

                entmsr_params = self.__parent.get_signal_result(Signals.ENTMSR_START, self)

                results = []
                self.__complete_pairs = 0
                self.__num_pairs = entmsr_params.num_pairs

                while self.__complete_pairs != self.__num_pairs:
                    yield self.await_port_output(self.node.ports["0"])
                    msg = self.node.ports["0"].rx_output()

                    assert msg.items and len(msg.items) == 1
                    pkt = msg.items[0]
                    packet = {}
                    if len(pkt) > 0:
                        packet["ethernet"] = pkt.pop()
                    if len(pkt) > 0:
                        packet["egp"] = pkt.pop()
                    if len(pkt) > 0:
                        packet["qnp"] = pkt.pop()
                    assert len(pkt) == 0

                    if "qnp" in packet:
                        request_id = packet["qnp"]["circuit_id"].val
                        bell_index = packet["qnp"]["bell_index"].val
                    else:
                        request_id = packet["egp"]["link_label"].val
                        bell_index = packet["egp"]["bell_index"].val

                    # In case there are some leftovers from the previous request.
                    if request_id != self.__parent.current_request_id:
                        logger.debug("%s::%s::DISCARD", self.node.name, packet)
                        self.node.qubit_discard(1)
                        continue

                    results.append((bell_index, self.node.qubit_measure(1)))
                    self.__complete_pairs += 1

                    # logger.info("%s::%s::MSR=%d", self.node.name, packet, results[-1][1])
                    print(f"{self.node.name}::{packet}::MSR={results[-1][1]}")

                # Request complete book keeping
                self.__complete_pairs = None
                self.__num_pairs = None
                self.send_signal(Signals.ENTMSR_COMPL, result=results)
