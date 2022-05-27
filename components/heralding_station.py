"""The MidPoint device."""
from copy import deepcopy
from dataclasses import dataclass

from netsquid.components.component import Component
from netsquid.protocols import NodeProtocol
from netsquid_p4.node import P4Node
from netsquid_p4_v1quantum import V1QuantumDevice, BsmOutcome
from netsquid_physlayer.detectors import BSMDetector

from util.rtt import RttProtocol


class HeraldingStation(P4Node):
    """The Heralding Station device.

    The Heralding Station device consists of one or more BSM detectors to provide heralded
    entanglement.

    Paramaters
    ----------
    name : `str`
        The name for this QNode.
    num_bsm_units : `int`, optional
        Number of BSM units. A port will be created and assigned to each BSM unit. The port names
        will be integers in the range 0-num_bsm_units. Default: 1.
    port_names : list of `str`, optional
        The names of the ports to add during construction.
    bsm_properties : {"p_dark": `float`, "det_eff": `float`, "visibility": `float`}
        Properties of the BSM detectors.

    """

    def __init__(self, name, num_bsm_units=1, port_names=None, bsm_properties=None):
        super().__init__(
            name,
            p4device=HeraldingDevice(f"{name}-heralding-device", self),
            port_names=port_names,
        )

        # Add a CPU port.
        self.add_ports(["0"])

        # Protocols on the physical layer classical ports.
        self.port_protocols = {}
        self.__install_custom_protocols(self.ports)

        # Add the BSM units.
        for bsm_index in range(num_bsm_units):
            self.add_subcomponent(
                BsmUnit(self, self.bsm_unit_name(bsm_index), bsm_index, bsm_properties)
            )

        # For keeping track of BSM groups.
        self.__bsm_group_ports = {}

    def __install_custom_protocols(self, ports):
        for name, port in ports.items():
            if name.startswith("cl-"):
                self.port_protocols[name] = PortProtocol(self, port).start()

    def bsm_unit_name(self, bsm_id):
        """Get the name for the BSM unit with the given ID.

        Parameters
        ----------
        bsm_id : `int`
            The ID of the BSM unit.

        Returns
        -------
        `str`
            The name of the BSM unit.

        """
        return f"{self.name}-BsmUnit-{bsm_id}"

    def connect_bsm(self, bsm_index, cl0, qu0, cl1, qu1):
        # pylint: disable=too-many-arguments
        # reason: the arguments are very basic - just lots of ports.
        bsm_unit = self.subcomponents[self.bsm_unit_name(bsm_index)]

        assert bsm_index not in self.__bsm_group_ports
        self.__bsm_group_ports[bsm_index] = (cl0, qu0, cl1, qu1)

        bsm_unit.cl0.forward_output(cl0)
        bsm_unit.cl1.forward_output(cl1)
        self.port_protocols[cl0.name].forward_input(bsm_unit.cl0)
        self.port_protocols[cl1.name].forward_input(bsm_unit.cl1)

        qu0.forward_input(bsm_unit.qu0)
        qu1.forward_input(bsm_unit.qu1)

        bsm_unit.start_heralding_protocol()

    def disconnect_bsm(self, bsm_index):
        assert bsm_index in self.__bsm_group_ports
        bsm_unit = self.subcomponents[self.bsm_unit_name(bsm_index)]
        cl0, qu0, cl1, qu1 = self.__bsm_group_ports.pop(bsm_index)

        bsm_unit.stop_heralding_protocol()

        bsm_unit.cl0.forward_output(None)
        bsm_unit.cl1.forward_output(None)
        self.port_protocols[cl0.name].forward_input(None)
        self.port_protocols[cl1.name].forward_input(None)

        qu0.forward_input(None)
        qu1.forward_input(None)

    def load(self, program_file_name):
        self.p4device.load(program_file_name)


class HeraldingDevice(V1QuantumDevice):

    def __init__(self, name, node, port_names=None):
        super().__init__(name, port_names=port_names)
        self.__node = node

    def create_bsm_group(self, group_id, bsm_group_entry_0, bsm_group_entry_1):
        """Create a BSM group.

        Parameters
        ----------
        group_id : `int`
            The BSM group ID.
        bsm_group_entry_0 : `pyp4_v1quantum.BsmGroupEntry`
            The first BSM group entry.
        bsm_group_entry_1 : `pyp4_v1quantum.BsmGroupEntry`
            The second BSM group entry.

        """
        super().create_bsm_group(group_id, bsm_group_entry_0, bsm_group_entry_1)
        self.__node.connect_bsm(
            group_id,
            self.__node.ports[f"cl-{bsm_group_entry_0.egress_port}"],
            self.__node.ports[f"qu-{bsm_group_entry_0.egress_port}"],
            self.__node.ports[f"cl-{bsm_group_entry_1.egress_port}"],
            self.__node.ports[f"qu-{bsm_group_entry_1.egress_port}"],
        )

    def destroy_bsm_group(self, group_id):
        """Destroy a BSM group.

        Parameters
        ----------
        group_id : `int`
            The BSM group ID.

        """
        self.__node.disconnect_bsm(group_id)
        super().destroy_bsm_group(group_id)


class PortProtocol(NodeProtocol):
    """Protocol for handling classical messages on the physical layer classical port.

    Parameters
    ----------
    node : `netsquid_p4.node.P4Node`
        The device on which this protocol is running.
    port : `~netsquid.components.component.Port`
        The port to listen on.

    """

    def __init__(self, node, port):
        super().__init__(node, f"{node.name}-PortProtocol-{port}")
        self.__port = port
        self.__forwarding_port = None

    def forward_input(self, port):
        """Forward unrecognised input to the given port.

        Parameters
        ----------
        port : `~netsquid.components.component.Port`
            The port to forward the input to.

        """
        self.__forwarding_port = port

    def __process_message(self, message):
        if isinstance(message, RttProtocol.Message) and (message.src != self.node.name):
            message.dst = self.node.name
            self.__port.tx_output(message)
        elif self.__forwarding_port is not None:
            self.__forwarding_port.tx_input(message)
        else:
            # Some messages may arrive during switchover of BSM groups.
            return

    def run(self):
        """Run the protocol."""
        while True:
            yield self.await_port_input(self.__port)

            message = self.__port.rx_input()
            while message is not None:
                for item in message.items:
                    self.__process_message(item)
                message = self.__port.rx_input()


class BsmUnit(Component):
    """A Bell state measurement unit.

    A BSM unit contains the BSM detector and runs the heralding protocol for that detector.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The QNode object.
    name : `str`
        The name for this protocol instance.
    bsm_id : `int`
        The ID of the BSM unit.
    bsm_properties : `dict`
        Additional properties of the BSM detector.

    """

    def __init__(self, node, name, bsm_id, bsm_properties=None):
        super().__init__(name, port_names=["cl0", "qu0", "cl1", "qu1"])

        bsm_properties = bsm_properties if bsm_properties is not None else {}
        bsm_detector = BSMDetector(name=f"{name}-BSMDetector", **bsm_properties)
        self.add_subcomponent(bsm_detector)
        self.qu0.forward_input(bsm_detector.ports["qin0"])
        self.qu1.forward_input(bsm_detector.ports["qin1"])

        self.__heralding_protocol = HeraldingProtocol(
            node, f"{name}-HeraldingProtocol", bsm_id, self.cl0, self.cl1, bsm_detector,
        )

    @property
    def cl0(self):
        """`~netsquid.components.component.Port`: The first physical layer classical port."""
        return self.ports["cl0"]

    @property
    def qu0(self):
        """`~netsquid.components.component.Port`: The first physical layer quantum port."""
        return self.ports["qu0"]

    @property
    def cl1(self):
        """`~netsquid.components.component.Port`: The second physical layer classical port."""
        return self.ports["cl1"]

    @property
    def qu1(self):
        """`~netsquid.components.component.Port`: The second physical layer quantum port."""
        return self.ports["qu1"]

    def start_heralding_protocol(self):
        """Start the heralding protocol on this unit."""
        assert not self.__heralding_protocol.is_running
        self.__heralding_protocol.reset()
        assert self.__heralding_protocol.is_running

    def stop_heralding_protocol(self):
        """Stop the heralding protocol on this unit."""
        assert self.__heralding_protocol.is_running
        self.__heralding_protocol.stop()
        assert not self.__heralding_protocol.is_running


@dataclass
class NewBsmGroup:
    """Message sent to the nodes to notify them of a new BSM group."""
    name: str
    bsm_id: int


@dataclass
class QNodeReady:
    """Message sent to the heralding station to signal a node's readiness."""
    name: str


@dataclass
class EntParams:
    """Message sent to the nodes with parameters for the entanglement."""
    alpha: float


class HeraldingProtocol(NodeProtocol):
    """The Heralding Station side of the Heralding Protocol.

    This protocol aligns with the `components.qnode.HeraldingProtocol`. Together, they implement the
    physical layer Heralding Protocol. The heralding station protocol will trigger the heralding
    event in the station's P4 program for each detection event. It also forwards the detection
    events to the nodes on either side of the link.

    One `heralding_station.HeraldingProtocol` runs on each active BSM unit.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The QNode object.
    name : `str`
        The name for this protocol instance.
    bsm_id : `int`
        The ID of the BSM unit.
    cl0 : `~netsquid.components.component.Port`
        The first classical physical layer port connected to the BSM unit this protocol runs on.
    cl1 : `~netsquid.components.component.Port`
        The second classical physical layer port connected to the BSM unit this protocol runs on.
    bsm_detector : `~netsquid_physlayer.detectors.BSMDetector`
        The BSM detector of the BSM unit this protocol runs on.

    """

    def __init__(self, node, name, bsm_id, cl0, cl1, bsm_detector):
        # pylint: disable=too-many-arguments
        # reason: the arguments are very basic.
        super().__init__(node, name)
        self.__bsm_id = bsm_id
        self.__cl0 = cl0
        self.__cl1 = cl1
        self.__bsm_detector = bsm_detector

    def run(self):
        """Run the heralding protocol."""
        # Start by sending a NewBsmGroup message. We are currently working with lossless channels so
        # we don't wait for an ACK.
        self.__cl0.tx_output(NewBsmGroup(name=self.node.name, bsm_id=self.__bsm_id))
        self.__cl1.tx_output(NewBsmGroup(name=self.node.name, bsm_id=self.__bsm_id))

        # Now we start the heralding loop.
        while True:
            # First thing we do is wait for a QNodeReady message from both sides.
            node_ready = [False, False]
            while not (node_ready[0] and node_ready[1]):
                yield self.await_port_input(self.__cl0) | self.await_port_input(self.__cl1)
                for port_i, msg in enumerate([self.__cl0.rx_input(), self.__cl1.rx_input()]):
                    if msg is not None:
                        assert len(msg.items) == 1
                        assert isinstance(msg.items[0], QNodeReady)
                        assert not node_ready[port_i]
                        node_ready[port_i] = True

            # Send the parameters of the next entanglement to generate.
            alpha = 0.3
            self.__cl0.tx_output(EntParams(alpha=alpha))
            self.__cl1.tx_output(EntParams(alpha=alpha))

            # Monitor the detector until there is a success.
            detector_port = self.__bsm_detector.ports["cout0"]
            success = False
            while not success:
                yield self.await_port_output(detector_port)

                message = detector_port.rx_output()
                assert len(message.items) == 1
                outcome = message.items[0]
                bsm_outcome = BsmOutcome(
                    bsm_id=self.__bsm_id,
                    success=outcome.success,
                    bell_index=V1QuantumDevice.from_netsquid_bell_index(outcome.bell_index),
                )

                self.__cl0.tx_output(deepcopy(bsm_outcome))
                self.__cl1.tx_output(deepcopy(bsm_outcome))
                self.node.p4device.heralding_bsm_outcome(bsm_outcome)

                success = outcome.success
