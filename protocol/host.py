"""The host protocol."""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import logging
from queue import Queue
from typing import Optional

from netsquid.protocols import NodeProtocol
import netsquid as ns
from pydynaa import EventType
from pyp4_v1quantum import V1QuantumBellIndex

from protocol.agent import Agent
from protocol.protocol import QcpMsg, QcpOp, RequestMsg


CTL_PORT = 0x200


logger = logging.getLogger(__name__)


class Signals(Enum):
    """Signals used by the Entangle and Measure protocol and its subprotocols."""
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
        """Internal request state."""
        request: 'EntangleAndMeasure.Request'
        request_time: float
        start_time: Optional[float] = None
        end_time: Optional[float] = None
        outcomes: Optional[list] = None

    def __init__(self, node, network_config):
        # pylint: disable=unused-argument
        super().__init__(node)
        self.__host = self.node.name

        self.add_subprotocol(EntangleAndMeasure.HostCommSubProtocol(node, self), "HOSTCOMM")
        self.add_subprotocol(EntangleAndMeasure.CtlPortSubProtocol(node), "CTLPORT")
        self.add_subprotocol(EntangleAndMeasure.AgentSubProtocol(node, self), "AGENT")
        self.add_subprotocol(EntangleAndMeasure.ReserveSubProtocol(node, self), "RESERVE")
        self.add_subprotocol(EntangleAndMeasure.ReleaseSubProtocol(node, self), "RELEASE")
        self.add_subprotocol(EntangleAndMeasure.EntMsrSubProtocol(node, self), "ENTMSR")

        for signal in Signals:
            self.add_signal(signal)

        self.__current_request_id = None
        self.__current_remote_id = None
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
        app0_results : `experiments.network.protocol.host.EntangleAndMeasure.RequestData`
            Results from one of the hosts.
        app1_results : `experiments.network.protocol.host.EntangleAndMeasure.RequestData`
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
        self.node.ports[str(new_request.remote)].tx_output(deepcopy(new_request))
        self.local_request(new_request)

    def local_request(self, new_request):
        """Insert the request into the local store.

        Parameters
        ----------
        new_request : `qp4_simulations.host.app.Request`
            The request.

        """
        request_data = EntangleAndMeasure.RequestData(
            request=new_request, request_time=ns.sim_time())
        self.__requests.put(request_data)
        if self.__requests.qsize() == 1:
            self.send_signal(Signals.RESTART)

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
            self.__current_remote_id = request.remote

            # Start by sending a message to the controller to reserve a circuit.
            self.send_signal(
                Signals.RESERVE_START,
                result=EntangleAndMeasure.ReserveSubProtocol.Params(
                    remote=request.remote,
                    request_id=request.request_id,
                )
            )
            yield self.await_signal(self.subprotocols["RESERVE"], Signals.RESERVE_COMPL)

            # Start time is the moment we start entangling.
            request_data.start_time = ns.sim_time()

            # Entangle and measure
            entmsr_params = EntangleAndMeasure.EntMsrSubProtocol.Params(
                request_id=request.request_id,
                remote_id=request.remote,
                num_pairs=request.parameters["num_pairs"],
            )
            self.send_signal(Signals.ENTMSR_START, result=entmsr_params)
            yield self.await_signal(self.subprotocols["ENTMSR"], Signals.ENTMSR_COMPL)
            request_data.outcomes = \
                self.subprotocols["ENTMSR"].get_signal_result(Signals.ENTMSR_COMPL, self)

            # End time is the moment entanglement completes.
            request_data.end_time = ns.sim_time()

            # The results are ready.
            self.__results[request.request_id] = request_data

            # Send a release now.
            self.send_signal(
                Signals.RELEASE_START,
                result=EntangleAndMeasure.ReleaseSubProtocol.Params(
                    remote=request.remote,
                    request_id=request.request_id,
                ),
            )
            yield self.await_signal(self.subprotocols["RELEASE"], Signals.RELEASE_COMPL)

            # Reset current request ID
            self.__current_request_id = None
            self.__current_remote_id = None

    class HostCommSubProtocol(NodeProtocol):
        """The inter-host communication subprotocol.

        This subprotocol listens on the ports leading to the other hosts and handles the messages.


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

        def run(self):
            """Run the subprotocol."""
            while True:
                # Listen on all host ports - recognised by port names that start with 'h'.
                event = None
                for port in filter(
                        lambda p: not (p.name.isdigit() or
                                       p.name.startswith("cl-") or
                                       p.name.startswith("qu")),
                        self.node.ports.values(),
                ):
                    if event is None:
                        event = self.await_port_input(port)
                    else:
                        event |= self.await_port_input(port)
                yield event

                for port in filter(
                        lambda p: not (p.name.isdigit() or
                                       p.name.startswith("cl-") or
                                       p.name.startswith("qu")),
                        self.node.ports.values(),
                ):
                    msg = port.rx_input()

                    # Because we must loop through all the ports to figure out which one triggered
                    # the event, some of them will return None.
                    if msg is not None:
                        assert msg.items is not None
                        assert len(msg.items) == 1
                        request = msg.items[0]
                        request.remote = port.name
                        self.__parent.local_request(msg.items[0])


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
                    print(f"{self.node.name}::{packet}::MSR={results[-1][1]}")

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
