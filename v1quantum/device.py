"""A basic quantum switch based on the v1quantum P4 architecture."""

from dataclasses import dataclass

from netsquid.qubits.ketstates import BellIndex
import netsquid as ns
from netsquid_p4.device import P4Device, NetsquidRuntime
import pyp4

from v1quantum.processor import (
    V1QuantumBellIndex,
    V1QuantumProcessor,
    V1QuantumRuntimeAbc,
    V1QuantumProcess,
    V1QuantumPortMeta,
)



@dataclass
class BsmOutcome:
    """A Bell State Measurement outcome."""
    bsm_id: int
    success: bool
    bell_index: V1QuantumBellIndex


class V1QuantumDevice(P4Device):
    """The V1Quantum architecture based device (NetSquid component).

    Parameters
    ----------
    name : `str`
        The name for this switch.
    runtime : `~pyp4_v1quantum.V1QuantumRuntimeAbc`, optional
        The runtime for this switch. If `None`, `netsquid_p4_v1quantum.V1QuantumRuntime` will be
        used.
    port_names : list of `str`, optional
        The names of the ports to add during construction.

    """

    def __init__(self, name, runtime=None, port_names=None):
        runtime = V1QuantumRuntime() if runtime is None else runtime
        p4_processor = V1QuantumProcessor(runtime)
        super().__init__(name, p4_processor, port_names=port_names)

    def _create_process(self, program):
        return V1QuantumProcess(f"{self.name}-V1QuantumProcess", program, pyp4.PacketIO.STACK)

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
        self._p4_processor.create_bsm_group(group_id, bsm_group_entry_0, bsm_group_entry_1)

    def destroy_bsm_group(self, group_id):
        """Destroy a BSM group.

        Parameters
        ----------
        group_id : `int`
            The BSM group ID.

        """
        self._p4_processor.destroy_bsm_group(group_id)

    def cnetwork_process(self, port_index, packet):
        """Process an incoming classical network packet.

        Parameters
        ----------
        port_index : `int`
            The port the packet arrived on.
        packet : `~pyp4.packet.HeaderStack`
            The incoming packet.

        """
        port_meta = V1QuantumPortMeta(
            pathway=self._p4_processor.PathWay["cnetwork"],
            standard_metadata={"ingress_port": port_index},
            qcontrol_metadata={},
        )
        port_packets = self._p4_processor.input(port_meta, packet)
        self.__execute(port_packets)

    def qdevice_process(self, qcontrol_metadata):
        """Process an incoming QControl event.

        Parameters
        ----------
        qcontrol_metadata : dict
            QControl metadata as a dict.

        """
        port_meta = V1QuantumPortMeta(
            pathway=self._p4_processor.PathWay["qcontrol"],
            standard_metadata={},
            qcontrol_metadata=qcontrol_metadata,
        )
        port_packets = self._p4_processor.input(port_meta, None)
        self.__execute(port_packets)

    def __execute(self, port_packets):
        for port_meta, packet in port_packets:
            if port_meta.pathway == self._p4_processor.PathWay["cnetwork"]:
                self._cnetwork_execute(port_meta.standard_metadata["egress_port"], packet)
            else:
                assert port_meta.pathway == self._p4_processor.PathWay["qcontrol"]
                assert packet is None
                self._qdevice_execute(port_meta.qcontrol_metadata)

    def _qdevice_execute(self, qcontrol_metadata):
        """Execute the relevant QControl processing from the received event.

        Parameters
        ----------
        qcontrol_metadata : dict
            The QControl metadata for the operation to execute.

        """
        # The V1Quantum architecture won't output anything for operation "none".
        raise NotImplementedError

    @staticmethod
    def from_netsquid_bell_index(ns_bell_index):
        """Convert the NetSquid Bell index to a V1Quantum Bell index.

        Parameters
        ----------
        ns_bell_index : `~netsquid.qubits.ketstates.BellIndex`
            The NetSquid Bell index.

        Returns
        -------
        `~pyp4_v1quantum.V1QuantumBellIndex` or None
            The V1Quantum Bell index (or None if the input was not a NetSquid Bell index).

        """
        if ns_bell_index == BellIndex.PHI_PLUS:
            return V1QuantumBellIndex.PHI_PLUS

        if ns_bell_index == BellIndex.PHI_MINUS:
            return V1QuantumBellIndex.PHI_MINS

        if ns_bell_index == BellIndex.PSI_PLUS:
            return V1QuantumBellIndex.PSI_PLUS

        if ns_bell_index == BellIndex.PSI_MINUS:
            return V1QuantumBellIndex.PSI_MINS

        return None

    def heralding_bsm_outcome(self, bsm_outcome):
        """Notify the processor of the heralding outcome.

        Parameters
        ----------
        bsm_outcome : `netsquid_p4_v1quantum.BsmOutcome`
            The BSM outcome.

        """
        qcontrol_metadata = {
            "event_type": self._p4_processor.QControlEventType["heralding_bsm_outcome"],
            "bsm_id": bsm_outcome.bsm_id,
            "bsm_success": int(bsm_outcome.success),
            "bsm_bell_index": int(bsm_outcome.bell_index) if bsm_outcome.success else 0,
        }
        self.qdevice_process(qcontrol_metadata)

    def swap_bsm_outcome(self, bsm_outcome, qubit_0, qubit_1):
        """Notify the processor of the swap outcome.

        Parameters
        ----------
        bsm_outcome : `netsquid_p4_v1quantum.BsmOutcome`
            The BSM outcome.
        qubit_0 : `int`
            The first qubit that was involved in the swap.
        qubit_1 : `int`
            The second qubit that was involved in the swap.

        """
        qcontrol_metadata = {
            "event_type": self._p4_processor.QControlEventType["swap_bsm_outcome"],
            "swap_bsm_id": bsm_outcome.bsm_id,
            "swap_qubit_0": qubit_0,
            "swap_qubit_1": qubit_1,
            "bsm_id": bsm_outcome.bsm_id,
            "bsm_success": int(bsm_outcome.success),
            "bsm_bell_index": int(bsm_outcome.bell_index) if bsm_outcome.success else 0,
        }
        self.qdevice_process(qcontrol_metadata)


class V1QuantumRuntime(V1QuantumRuntimeAbc, NetsquidRuntime):
    """The simulation runtime for the V1Quantum switch."""

    def __init__(self):
        V1QuantumRuntimeAbc.__init__(self)
        NetsquidRuntime.__init__(self, ns.NANOSECOND)

    def time(self):
        """Get the simulated time.

        Returns
        -------
        `int`
            The current time on the device in nanoseconds. The clock must be set to 0 every time the
            switch starts.

        """
        return NetsquidRuntime.time(self)
