"""The host protocol."""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from functools import reduce
import logging
from queue import Queue
from typing import Optional

from netsquid_netrunner.loaders.demand import NetworkApp
from netsquid.protocols import NodeProtocol
import netsquid as ns
from pydynaa import EventType, EventHandler
from pyp4_v1quantum import V1QuantumBellIndex

from protocol.control_plane.agent import Agent
from protocol.control_plane.protocol import QcpMsg, QcpOp, RequestMsg


CTL_PORT = 0x200


logger = logging.getLogger(__name__)


class Signals(Enum):
    """Signals used by the Entangle and Measure protocol and its subprotocols."""
    HANDSHAKE_START = EventType("HANDSHAKE_START", "Initiate host handshake")
    HANDSHAKE_COMPL = EventType("HANDSHAKE_COMPL", "Host handshake complete")
    RESERVE_START = EventType("RESERVE_START", "Reserve a BSM group")
    RESERVE_COMPL = EventType("RESERVE_COMPL", "BSM group reserved")
    ENTMSR_START = EventType("ENTMSR_START", "Entangle and measure")
    ENTMSR_COMPL = EventType("ENTMSR_COMPL", "Entangle and measure complete")
    RELEASE_START = EventType("RELEASE_START", "Release a BSM group")
    RELEASE_COMPL = EventType("RELEASE_COMPL", "BSM group released")
    CTL_RSRV_MSG = EventType("CTL_RSRV_MSG", "RSRV message from controller")
    CTL_FREE_MSG = EventType("CTL_FREE_MSG", "FREE message from controller")
    CTL_RULE_MSG = EventType("CTL_RULE_MSG", "RULE message from controller")
    RESTART = EventType("RESTART", "There is work to do")


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
        handshake_attempts: int = 0
        remote_ready: bool = False

    @dataclass
    class RequestResults:
        """Internal request state."""
        request_time: float
        start_time: Optional[float] = None
        end_time: Optional[float] = None
        outcomes: Optional[list] = None

    @dataclass
    class Handshake:
        """Handshake message."""
        request: NetworkApp
        remote_ready: bool = False

    def __init__(self, node, network_config):
        # pylint: disable=unused-argument
        super().__init__(node)
        self.__host = self.node.name
        self.random = ns.get_random_state()

        self.add_subprotocol(EntangleAndMeasure.CtlPortSubProtocol(node), "CTLPORT")
        self.add_subprotocol(EntangleAndMeasure.AgentSubProtocol(node, self), "AGENT")
        self.add_subprotocol(EntangleAndMeasure.HandshakeSubProtocol(node, self), "HANDSHAKE")
        self.add_subprotocol(EntangleAndMeasure.ReserveSubProtocol(node, self), "RESERVE")
        self.add_subprotocol(EntangleAndMeasure.ReleaseSubProtocol(node, self), "RELEASE")
        self.add_subprotocol(EntangleAndMeasure.EntMsrSubProtocol(node, self), "ENTMSR")

        for signal in Signals:
            self.add_signal(signal)

        self.__current_request_id = None
        self.__current_remote_id = None
        self.__reattempts = {}
        self.__requests = Queue()
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
        request_data = EntangleAndMeasure.RequestData(
            request=new_request,
            results=EntangleAndMeasure.RequestResults(request_time=ns.sim_time()),
        )
        self.enqueue_request(request_data)

    def reattempt_request_after(self, request_data, delay):
        """Insert the request into the local store after the provided delay.

        Parameters
        ----------
        request_data : `qp4_simulations.host.app.Request`
            The request.
        delay : `float`
            The delay.

        """
        event = self._schedule_after(delay, EventType("ENQUEUE_REQUEST", "enqueue_request"))
        self.__reattempts[event.id] = request_data
        self._wait_once(EventHandler(self.reattempt_enqueue_request), entity=self, event=event)

    def reattempt_enqueue_request(self, event):
        """Insert the request into the local store.

        Parameters
        ----------
        request_data : `qp4_simulations.host.app.Request`
            The request.

        """
        request_data = self.__reattempts.pop(event.id)
        self.enqueue_request(request_data)

    def enqueue_request(self, request_data):
        """Insert the request into the local store.

        Parameters
        ----------
        request_data : `qp4_simulations.host.app.Request`
            The request.

        """
        self.__requests.put(request_data)
        if self.__requests.qsize() == 1:
            self.send_signal(Signals.RESTART)

    def is_idle(self):
        return (self.__current_request_id is None)

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
            if self.__requests.empty():
                yield self.await_signal(self, Signals.RESTART)

            # Get the next request
            assert not self.__requests.empty()
            request_data = self.__requests.get()
            request = request_data.request

            assert request.request_id not in self.__results
            self.__current_request_id = request.request_id
            self.__current_remote_id = request.node1

            # First handshake with the other host.
            if not request_data.remote_ready:
                self.send_signal(Signals.HANDSHAKE_START, result=request_data)
                yield self.await_signal(self.subprotocols["HANDSHAKE"], Signals.HANDSHAKE_COMPL)
                request_data = self.subprotocols["HANDSHAKE"].get_signal_result(
                    Signals.HANDSHAKE_COMPL, self)

                # The request has been enqueued for a reattempt.
                if request_data is None:
                    self.__current_request_id = None
                    self.__current_remote_id = None
                    continue

            # Verify assumption.
            assert request_data.remote_ready

            # Send a message to the controller to reserve a circuit.
            self.send_signal(
                Signals.RESERVE_START,
                result=EntangleAndMeasure.ReserveSubProtocol.Params(
                    remote=request.node1,
                    request_id=request.request_id,
                )
            )
            yield self.await_signal(self.subprotocols["RESERVE"], Signals.RESERVE_COMPL)

            # Start time is the moment we start entangling.
            request_data.results.start_time = ns.sim_time()

            # Entangle and measure
            entmsr_params = EntangleAndMeasure.EntMsrSubProtocol.Params(
                request_id=request.request_id,
                remote_id=request.node1,
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
            self.send_signal(
                Signals.RELEASE_START,
                result=EntangleAndMeasure.ReleaseSubProtocol.Params(
                    remote=request.node1,
                    request_id=request.request_id,
                ),
            )
            yield self.await_signal(self.subprotocols["RELEASE"], Signals.RELEASE_COMPL)

            # Reset current request ID
            self.__current_request_id = None
            self.__current_remote_id = None

    class HandshakeSubProtocol(NodeProtocol):
        """The inter-host handshake subprotocol.

        This subprotocol listens on the ports leading to the other hosts and handles handshake
        messages.


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
            self.__request_data = None
            self.__origin_handhshake_send_time = None
            self.add_signal(Signals.HANDSHAKE_START)
            self.add_signal(Signals.HANDSHAKE_COMPL)

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

        def __send_local_origin_handshake(self):
            assert not self.__request_data.remote_ready
            self.__request_data.handshake_attempts += 1
            handshake = EntangleAndMeasure.Handshake(request=deepcopy(self.__request_data.request))
            self.node.ports[str(handshake.request.node1)].tx_output(handshake)
            self.__origin_handhshake_send_time = ns.sim_time()

        def __process_local_origin_handshake(self, handshake):
            if not handshake.remote_ready:
                self.__parent.reattempt_request_after(
                    self.__request_data,
                    (2 ** min(self.__request_data.handshake_attempts-1, 3)) *
                    (1.0 + self.__parent.random.random_sample()) *
                    (ns.sim_time() - self.__origin_handhshake_send_time),
                )
                self.__request_data = None
            else:
                self.__request_data.remote_ready = True

        def __process_remote_origin_handshake(self, rx_port, handshake):
            if self.__parent.is_idle():
                request = deepcopy(handshake.request)
                request.node0, request.node1 = request.node1, request.node0
                request_data = EntangleAndMeasure.RequestData(
                    request=request,
                    results=EntangleAndMeasure.RequestResults(request_time=ns.sim_time()),
                    remote_ready=True,
                )
                self.__parent.enqueue_request(request_data)
                handshake.remote_ready = True
            else:
                handshake.remote_ready = False

            rx_port.tx_output(handshake)

        def run(self):
            """Run the subprotocol."""
            while True:
                event = self.__await_host_port_input() | \
                    self.await_signal(self.__parent, Signals.HANDSHAKE_START)
                yield event

                assert len(event.triggered_events) == 1
                if event.triggered_events[0].type.name == Signals.HANDSHAKE_START.name:
                    assert self.__request_data is None

                    self.__request_data = self.__parent.get_signal_result(
                        Signals.HANDSHAKE_START, self)
                    self.__send_local_origin_handshake()

                    continue

                for port in self.__host_ports():
                    msg = port.rx_input()

                    # Because we must loop through all the ports to figure out which one triggered
                    # the event, some of them will return None.
                    if msg is not None:
                        assert msg.items is not None
                        for handshake in msg.items:
                            if handshake.request.node1 == self.node.name:
                                self.__process_remote_origin_handshake(port, handshake)
                            else:
                                assert handshake.request.node0 == self.node.name
                                self.__process_local_origin_handshake(handshake)

                                self.send_signal(Signals.HANDSHAKE_COMPL, result=self.__request_data)
                                self.__request_data = None


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
                    self.send_signal(Signals.CTL_RSRV_MSG, result=rsrv_items)
                if free_items:
                    self.send_signal(Signals.CTL_FREE_MSG, result=free_items)
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

    class ReserveSubProtocol(NodeProtocol):
        """The Reserve subprotocol.

        Parameters
        ----------
        node : `~netsquid.nodes.Node`
            The node running this subprotocol.
        parent : `~netsquid.protocols.NodeProtocol`
            The parent protocol.

        """

        @dataclass
        class Params:
            """Parameters for the Reserve subprotocol."""
            remote: str
            request_id: int

        def __init__(self, node, parent):
            super().__init__(node)

            self.__parent = parent

            self.add_signal(Signals.RESERVE_START)
            self.add_signal(Signals.RESERVE_COMPL)
            self.add_signal(Signals.CTL_RSRV_MSG)

        def run(self):
            """Run the Reserve subprotocol."""
            while True:
                yield self.await_signal(self.__parent, Signals.RESERVE_START)
                params = self.__parent.get_signal_result(Signals.RESERVE_START, self)
                assert params is not None

                # Start by sending a message to the controller to reserve a circuit.
                reserve = RequestMsg(
                    msg_type=QcpOp.OP_RSRV,
                    source=self.__parent.host,
                    remote=params.remote,
                    request_id=params.request_id,
                )

                # Send the message to the heralding station.
                self.node.ports[str(CTL_PORT)].tx_output(reserve)

                # Wait for a response.
                ctlport = self.__parent.subprotocols["CTLPORT"]
                yield self.await_signal(ctlport, Signals.CTL_RSRV_MSG)
                items = ctlport.get_signal_result(Signals.CTL_RSRV_MSG, self)

                # Check the contents of the returned message.
                assert items and len(items) == 1
                msg = items[0]

                assert msg.msg_type == QcpOp.OP_RSRV
                assert msg.source == self.__parent.host
                assert msg.remote == params.remote
                assert msg.request_id == params.request_id

                self.send_signal(Signals.RESERVE_COMPL)

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
                    # print(f"{self.node.name}::{packet}::MSR={results[-1][1]}")

                # Request complete book keeping
                self.__complete_pairs = None
                self.__num_pairs = None
                self.send_signal(Signals.ENTMSR_COMPL, result=results)

    class ReleaseSubProtocol(NodeProtocol):
        """The Release subprotocol.

        Parameters
        ----------
        node : `~netsquid.nodes.Node`
            The node running this subprotocol.
        parent : `~netsquid.protocols.NodeProtocol`
            The parent protocol.

        """

        @dataclass
        class Params:
            """Parameters for the Release subprotocol."""
            remote: str
            request_id: int

        def __init__(self, node, parent):
            super().__init__(node)

            self.__parent = parent

            self.add_signal(Signals.RELEASE_START)
            self.add_signal(Signals.RELEASE_COMPL)
            self.add_signal(Signals.CTL_FREE_MSG)

        def run(self):
            """Run the Release subprotocol."""
            while True:
                yield self.await_signal(self.__parent, Signals.RELEASE_START)
                params = self.__parent.get_signal_result(Signals.RELEASE_START, self)
                assert params is not None

                # Send a release now.
                release = RequestMsg(
                    msg_type=QcpOp.OP_FREE,
                    source=self.__parent.host,
                    remote=params.remote,
                    request_id=params.request_id,
                )

                # Send the message to the controller.
                self.node.ports[str(CTL_PORT)].tx_output(release)

                # Wait for a response.
                ctlport = self.__parent.subprotocols["CTLPORT"]
                yield self.await_signal(ctlport, Signals.CTL_FREE_MSG)
                items = ctlport.get_signal_result(Signals.CTL_FREE_MSG, self)

                # Check the contents of the returned message.
                assert items and len(items) == 1
                msg = items[0]

                assert msg.msg_type == QcpOp.OP_FREE
                assert msg.source == self.__parent.host
                assert msg.remote == params.remote
                assert msg.request_id == params.request_id

                self.send_signal(Signals.RELEASE_COMPL)
