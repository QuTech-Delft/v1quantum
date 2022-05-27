"""The QNode device."""

from netsquid.components.qprocessor import QuantumProcessor
from netsquid.protocols import NodeProtocol
from netsquid.protocols.protocol import Signals
from netsquid.qubits import operators
import netsquid as ns
from netsquid_physlayer.pair_preparation import ExcitedPairPreparation
from pydynaa import EventHandler, EventType
from pyp4_v1quantum import V1QuantumBellIndex
from netsquid_p4.node import P4Node
from netsquid_p4_v1quantum import V1QuantumDevice, BsmOutcome

from components.heralding_station import QNodeReady
from util.rtt import RttProtocol


class QNode(P4Node):

    def __init__(self, name, nqubits=1, port_names=None):
        super().__init__(
            name,
            p4device=QDevice(f"{name}-qdevice", self),
            qmemory=QuantumProcessor(name=f"{name}-qproc", num_positions=nqubits),
            port_names=port_names,
        )

        # Add a CPU port.
        self.add_ports(["0"])

        # Install the protocols.
        self.__heralding_protocols = {}
        self.__install_protocols(self.ports)

    def __install_protocols(self, ports):
        # QNode runs heralding protocols on the cl- and qu- ports.
        for name in ports.keys():
            if name.startswith("cl-"):
                index = int(name[3:], 0)

                assert index is not None
                assert f"qu-{index}" in ports.keys()

                self.__heralding_protocols[index] = HeraldingProtocol(
                    self,
                    f"{self.name}-HeraldingProtocol-{index}",
                    index,
                    ports[f"cl-{index}"],
                    ports[f"qu-{index}"],
                ).start()

    def qubit_discard(self, qubit):
        """Discard a qubit.

        Parameters
        ----------
        qubit : `int`
            The ID of the qubit to discard.

        """
        self.__heralding_protocols[qubit].signal_qubit_free()
        self.qmemory.measure(QNode.qubit_position(qubit), discard=True)

    def qubit_measure(self, qubit):
        """Measure a qubit.

        Parameters
        ----------
        qubit : `int`
            The ID of the qubit to discard.

        Returns
        -------
        `int`
            The result of the measurement.

        """
        self.__heralding_protocols[qubit].signal_qubit_free()
        return self.qmemory.measure(QNode.qubit_position(qubit), discard=True)[0][0]

    @staticmethod
    def qubit_position(qubit):
        """Map a qubit ID to its memory position.

        Parameters
        ----------
        qubit : `int`
            The ID of the qubit.

        Returns
        -------
        `int`
            The qubit's position in memory.

        """
        return qubit - 1

    def execute_swap(self, bsm_id, qubit_0, qubit_1):
        position_0 = QNode.qubit_position(qubit_0)
        position_1 = QNode.qubit_position(qubit_1)

        self.qmemory.operate(operators.CX, [position_0, position_1])
        self.qmemory.operate(operators.H, position_0)

        bsm_0 = self.qubit_measure(qubit_0)
        bsm_1 = self.qubit_measure(qubit_1)

        # Convert into a Bell index.
        bell_index = V1QuantumBellIndex(2*bsm_1 + bsm_0)

        # Since we are executing a zero-time swap we need to schedule the event to prevent
        # re-entrant code causing all kinds of bugs.
        self._wait_once(
            EventHandler(lambda event: self.p4device.swap_bsm_outcome(
                BsmOutcome(bsm_id=bsm_id, success=True, bell_index=bell_index), qubit_0, qubit_1,
            )),
            entity=self,
            event=self._schedule_now(EventType("SWAP", "Swap")),
        )

    def load(self, program_file_name):
        return self.p4device.load(program_file_name)


class QDevice(V1QuantumDevice):
    """The QNode device.

    The QNode device is a V1Quantum architecture device capable of generating photons entangled with
    one of their local qubits.

    Parameters
    ----------
    name : `str`
        The name for this QNode.
    port_names : list of `str`, optional
        The names of the ports to add during construction.

    """

    def __init__(self, name, node, port_names=None):
        super().__init__(name, port_names=port_names)
        self.__node = node

    def _qdevice_execute(self, qdevice_metadata):
        if qdevice_metadata["operation"] == self._p4_processor.QDeviceOperation["release"]:
            self.__node.qubit_discard(qdevice_metadata["release_qubit"])

        elif qdevice_metadata["operation"] == self._p4_processor.QDeviceOperation["swap"]:
            self.__node.execute_swap(
                qdevice_metadata["swap_bsm_id"],
                qdevice_metadata["swap_qubit_0"],
                qdevice_metadata["swap_qubit_1"],
            )

        else:
            raise NotImplementedError


class HeraldingProtocol(NodeProtocol):
    """The QNode side of the Heralding Protocol.

    This protocol aligns with the `netsquid_p4.devices.heralding_station.HeraldingProtocol`.
    Together, they implement the physical layer Heralding Protocol. The QNode protocol will trigger
    the heralding event in the QNode's P4 program for each heralding message it receives from the
    heralding station. This event will have exactly the same information filled out as the heralding
    event at the heralding station itself.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The QNode object.
    name : `str`
        The name for this protocol instance.
    index : `int`
        The port index for this protocol instance.
    clport : `~netsquid.components.component.Port`
        The classical port on which to run this protocol.
    quport : `~netsquid.components.component.Port`
        The quantum port on which to run this protocol.

    """

    def __init__(self, node, name, index, clport, quport):
        super().__init__(node, name)

        self.__qubit = index
        self.__position = QNode.qubit_position(self.__qubit)

        self.__clport = clport
        self.__quport = quport

        self.add_signal(self.__signal_label)
        self.__wait_for_bsm_group = True

    @property
    def __signal_label(self):
        return f"QBIT_FREE_{self.__qubit}"

    def signal_qubit_free(self):
        """Signal the protocol that the qubit for this interface has been freed."""
        self.send_signal(self.__signal_label)

    def __restart(self):
        # Because resetting from within is a dangerous game.
        self._wait_once(EventHandler(lambda event: self.reset()),
                        entity=self,
                        event=self._schedule_now(EventType("RESET", "Reset")))

    def __timeout(self):
        self.__wait_for_bsm_group = True
        self.__restart()

    def __new_bsm_group(self):
        self.__wait_for_bsm_group = False
        self.__restart()

    def run(self):
        """Run the heralding protocol."""
        # Start by waiting for a NewBsmGroup message.
        if self.__wait_for_bsm_group:
            yield self.await_port_input(self.__clport)
            msg = self.__clport.rx_input()
            assert msg is not None
            assert len(msg.items) == 1
            assert msg.items[0].__class__.__name__ == "NewBsmGroup"
            self.__wait_for_bsm_group = False

        # Estimate the RTT next.
        rtt_prot = RttProtocol(self.node, self.__clport).start()
        yield self.await_signal(rtt_prot, Signals.FINISHED)
        rtt = rtt_prot.get_signal_result(Signals.FINISHED)
        rtt_prot.remove()

        # Start the heralding loop.
        while True:
            # We proceed only if our qubit is free.
            while self.__position in self.node.qmemory.used_positions:
                yield (self.await_port_input(self.__clport) |
                       self.await_signal(self, self.__signal_label))

                # The only message the protocol should be sending is NewBsmGroup if it changed.
                msg = self.__clport.rx_input()
                if msg is not None:
                    assert len(msg.items) == 1
                    assert msg.items[0].__class__.__name__ == "NewBsmGroup"
                    self.__new_bsm_group()
                    return

            # Otherwise the qubit must have become free so let's drain the signal.
            self.get_signal_result(self.__signal_label)

            # Beyond this point the qubit MUST be free.
            assert self.__position in self.node.qmemory.unused_positions

            # Send a ready message.
            self.__clport.tx_output(QNodeReady(name=self.node.name))

            # Wait for a reply with the entanglement parameters.
            yield self.await_port_input(self.__clport)
            msg = self.__clport.rx_input()
            assert msg is not None
            assert len(msg.items) == 1

            # A NewBsmGroup message means we need reset the protocol.
            if msg.items[0].__class__.__name__ == "NewBsmGroup":
                self.__new_bsm_group()
                return

            # Otherwise we expect an EntParams.
            assert msg.items[0].__class__.__name__ == "EntParams"
            generator = ExcitedPairPreparation()
            alpha = msg.items[0].alpha

            # Start the main attempt loop until a success is received.
            while True:
                # Create and emit qubit-photon entanglement.
                qubit, photon = generator.generate(alpha)
                self.node.qmemory.put(qubit, positions=self.__position, replace=False)
                self.__quport.tx_output(photon)

                # Wait for heralding signal or timeout.
                yield self.await_port_input(self.__clport) | self.await_timer(rtt + ns.MICROSECOND)
                msg = self.__clport.rx_input()

                # Break heralding loop if the heralding station stopped sending anything.
                if msg is None:
                    self.node.qubit_discard(self.__qubit)
                    self.__timeout()
                    return

                # A NewBsmGroup message means we need reset the protocol.
                assert len(msg.items) == 1
                if msg.items[0].__class__.__name__ == "NewBsmGroup":
                    self.node.qubit_discard(self.__qubit)
                    self.__new_bsm_group()
                    return

                # Otherwise, we actually got a heralding message to process.
                assert msg.items[0].__class__.__name__ == "BsmOutcome"
                bsm_outcome = msg.items[0]

                # On a failure we discard the qubit, on a success we break the attempt loop. In both
                # cases we notify the node of the outcome, but in case of failure we need to make
                # sure to free the qubit first in case the node has other plans for it.
                if not bsm_outcome.success:
                    self.node.qubit_discard(self.__qubit)
                    self.node.p4device.heralding_bsm_outcome(bsm_outcome)
                else:
                    self.node.p4device.heralding_bsm_outcome(bsm_outcome)
                    break
