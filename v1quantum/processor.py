"""V1Quantum processor."""

from dataclasses import dataclass
from enum import IntEnum

from pyp4 import PacketIO
from pyp4.process import Process
from pyp4.processor import Processor
from pyp4.processors.v1model import V1ModelRuntimeAbc, V1ModelExtern


class V1QuantumBellIndex(IntEnum):
    """Bell state encoding."""
    PHI_PLUS = 0b00
    PHI_MINS = 0b01
    PSI_PLUS = 0b10
    PSI_MINS = 0b11


@dataclass
class BsmGroupEntry:
    """A single entry in a BSM multicast group."""

    egress_port: int
    bsm_info: int


class V1QuantumProcessor(Processor):
    """Processor for the V1Quantum architecture.

    The v1quantum architecture is intended to be a strictly quantum capable, super-set of the
    v1model architecture described in
    https://github.com/p4lang/p4c/blob/master/p4include/v1model.p4.

    Parameters
    ----------
    runtime : `pyp4.processors.v1quantum.V1QuantumRuntimeAbc`
        The runtime instance for the V1Quantum.

    """

    def __init__(self, runtime):
        # This processor requires a runtime
        assert runtime is not None
        super().__init__(runtime)
        self.__bsm_groups = {}

    @property
    def QDeviceEventType(self):
        """Return the QDeviceEventType enum dict."""
        # pylint:disable=invalid-name
        return self._process.enums["QDeviceEventType"]

    @property
    def QDeviceOperation(self):
        """Return the QDeviceOperation enum dict."""
        # pylint:disable=invalid-name
        return self._process.enums["QDeviceOperation"]

    @property
    def PathWay(self):
        """Return the PathWay enum dict."""
        # pylint:disable=invalid-name
        return self._process.enums["PathWay"]

    @property
    def __parser(self):
        return self._process.parsers["parser"]

    @property
    def __ingress(self):
        return self._process.blocks["ingress"]

    @property
    def __qdevice(self):
        return self._process.blocks["qdevice"]

    @property
    def __egress(self):
        return self._process.blocks["egress"]

    @property
    def __deparser(self):
        return self._process.deparsers["deparser"]

    @staticmethod
    def __check_field(field_name, input_meta, metadata_name):
        if field_name not in input_meta:
            raise ValueError(f"Field {field_name} was not provided in {metadata_name}")

    def __initialise_metadata(self, bus, port_in_meta):
        standard_metadata = bus.metadata["standard_metadata"]
        qdevice_metadata = bus.metadata["qdevice_metadata"]
        xconnect_metadata = bus.metadata["xconnect_metadata"]

        # Check the provided standard_metadata.
        if port_in_meta.pathway == self.PathWay["cnetwork"]:
            V1QuantumProcessor.__check_field(
                "ingress_port", port_in_meta.standard_metadata, "standard_metadata")

        # Copy over the input standard_metadata.
        for field, value in port_in_meta.standard_metadata.items():
            standard_metadata[field].val = value

        # Initialise certain fields to architecture-specific values.
        standard_metadata["egress_spec"].set_max_val()

        # Check the provided qdevice_metadata.
        if port_in_meta.pathway == self.PathWay["qdevice"]:
            V1QuantumProcessor.__check_field(
                "event_type", port_in_meta.qdevice_metadata, "qdevice_metadata")
            event_type = qdevice_metadata["event_type"].val
            if event_type in (self.QDeviceEventType["heralding_bsm_outcome"],
                              self.QDeviceEventType["swap_bsm_outcome"]):
                V1QuantumProcessor.__check_field(
                    "bsm_id", port_in_meta.qdevice_metadata, "qdevice_metadata")
                V1QuantumProcessor.__check_field(
                    "bsm_success", port_in_meta.qdevice_metadata, "qdevice_metadata")
                V1QuantumProcessor.__check_field(
                    "bsm_bell_index", port_in_meta.qdevice_metadata, "qdevice_metadata")

        # Copy over the input qdevice_metadata.
        for field, value in port_in_meta.qdevice_metadata.items():
            qdevice_metadata[field].val = value

        # Initialise certain fields to architecture-specific values.
        if port_in_meta.pathway == self.PathWay["cnetwork"]:
            qdevice_metadata["event_type"].val = self.QDeviceEventType["cnetwork"]
        qdevice_metadata["operation"].val = self.QDeviceOperation["none"]

        # Xconnect metadata is not provided by the user. We initialise its values.
        xconnect_metadata["pathway"].val = port_in_meta.pathway
        xconnect_metadata["ingress_port"].val = standard_metadata["ingress_port"].val
        xconnect_metadata["egress_spec"].set_max_val()
        xconnect_metadata["bsm_grp"].set_max_val()
        xconnect_metadata["bsm_info"].set_max_val()

    def __traffic_manager(self, bus):
        bus_list = []

        # We look at pathway as QDevice is not supposed to be setting it.
        if bus.metadata["xconnect_metadata"]["pathway"].val == self.PathWay["cnetwork"]:
            if not bus.metadata["standard_metadata"]["egress_spec"].is_max_val():
                bus_list.append(bus)

        else:
            assert bus.metadata["xconnect_metadata"]["pathway"].val == self.PathWay["qdevice"]

            if not bus.metadata["xconnect_metadata"]["egress_spec"].is_max_val():
                eg_bus = bus.clone()
                eg_bus.metadata["standard_metadata"]["egress_spec"].val = \
                    eg_bus.metadata["xconnect_metadata"]["egress_spec"].val
                bus_list.append(eg_bus)

            if (not bus.metadata["xconnect_metadata"]["bsm_grp"].is_max_val() and
                    bus.metadata["xconnect_metadata"]["bsm_grp"].val in self.__bsm_groups):
                bus_0 = bus.clone()
                bus_1 = bus.clone()

                bsm_group_id = bus.metadata["xconnect_metadata"]["bsm_grp"].val
                bsm_group = self.__bsm_groups[bsm_group_id]

                bus_0.metadata["standard_metadata"]["egress_spec"].val = bsm_group[0].egress_port
                bus_0.metadata["xconnect_metadata"]["bsm_info"].val = bsm_group[0].bsm_info

                bus_1.metadata["standard_metadata"]["egress_spec"].val = bsm_group[1].egress_port
                bus_1.metadata["xconnect_metadata"]["bsm_info"].val = bsm_group[1].bsm_info

                bus_list.append(bus_0)
                bus_list.append(bus_1)

        return bus_list

    def __egress_process(self, bus_list):
        for bus in bus_list:
            bus.metadata["standard_metadata"]["egress_port"].val = \
                bus.metadata["standard_metadata"]["egress_spec"].val
            bus.metadata["standard_metadata"]["egress_global_timestamp"].val = \
                int(self._runtime.time())

            self.__egress.process(bus)

            if bus.metadata["standard_metadata"]["egress_spec"].is_max_val():
                bus.packet.clear()

    def __emit(self, bus_packet_out_list):
        port_packet_out = []
        for bus, packet in bus_packet_out_list:
            port_out_meta = V1QuantumPortMeta(
                pathway=self.PathWay["qdevice"] if packet is None else self.PathWay["cnetwork"],
                standard_metadata=bus.metadata["standard_metadata"].as_dict(),
                qdevice_metadata=bus.metadata["qdevice_metadata"].as_dict(),
            )
            port_packet_out.append((port_out_meta, packet))

        return port_packet_out

    def create_bsm_group(self, group_id, bsm_group_entry_0, bsm_group_entry_1):
        """Create a BSM group.

        Parameters
        ----------
        group_id : `int`
            The BSM group ID.
        bsm_group_entry_0 : `pyp4.processors.v1quantum.BsmGroupEntry`
            The first BSM group entry.
        bsm_group_entry_1 : `pyp4.processors.v1quantum.BsmGroupEntry`
            The second BSM group entry.

        """
        self.__bsm_groups[group_id] = (bsm_group_entry_0, bsm_group_entry_1)

    def destroy_bsm_group(self, group_id):
        """Destroy a BSM group.

        Parameters
        ----------
        group_id : `int`
            The BSM group ID.

        """
        del self.__bsm_groups[group_id]

    def input(self, port_in_meta, packet_in):
        """Process an incoming packet.

        The input packet is consumed and the output packets are brand new object.

        Parameters
        ----------
        port_in_meta : `pyp4.processors.v1quantum.V1QuantumPortMeta`
            Input port metadata.
        packet_in : `<process specific Packet>`
            The input packet.

        Returns
        -------
        list of tuple of (`pyp4.processors.v1model.V1QuantumPortMeta`, `<process specific Packet`)
            One tuple of the output port metadata and the packet for each output packet

        """
        bus = self._process.bus()

        # ------------------------------------------------------------------------------------------
        # Initialise metadata.
        # ------------------------------------------------------------------------------------------

        self.__initialise_metadata(bus, port_in_meta)

        # ------------------------------------------------------------------------------------------
        # From the metadata we infer whether this packet should go through the CNetwork parser or
        # directly enter the QDevice cross connect.
        # ------------------------------------------------------------------------------------------

        if port_in_meta.pathway == self.PathWay["cnetwork"]:

            # --------------------------------------------------------------------------------------
            # Parser
            # --------------------------------------------------------------------------------------

            self.__parser.process(bus, packet_in)

            # --------------------------------------------------------------------------------------
            # CNetwork Ingress
            # --------------------------------------------------------------------------------------

            bus.metadata["standard_metadata"]["ingress_global_timestamp"].val = \
                int(self._runtime.time())
            self.__ingress.process(bus)

            # In case the ingress has redirected the bus to the qdevice we indicate this.
            bus.metadata["qdevice_metadata"]["event_type"].val = self.QDeviceEventType["cnetwork"]

        # ------------------------------------------------------------------------------------------
        # We enter the cross connect if the pathway in cross connect metadata indicates so. Note
        # that if the ingress wasn't invoked we expect this metadata field to be set when
        # initialising metadata.
        # ------------------------------------------------------------------------------------------

        if bus.metadata["xconnect_metadata"]["pathway"].val == self.PathWay["qdevice"]:
            # Make sure QDeviceOperation is set to none.
            bus.metadata["qdevice_metadata"]["operation"].val = self.QDeviceOperation["none"]

            # --------------------------------------------------------------------------------------
            # QDevice Cross Connect
            # --------------------------------------------------------------------------------------
            bus.metadata["qdevice_metadata"]["event_timestamp"].val = int(self._runtime.time())
            self.__qdevice.process(bus)

        # ------------------------------------------------------------------------------------------
        # Final egress processing.
        # ------------------------------------------------------------------------------------------

        bus_packet_out_list = []

        if bus.metadata["qdevice_metadata"]["operation"].val != self.QDeviceOperation["none"]:
            bus_packet_out_list.append((bus.clone(), None))

        # ------------------------------------------------------------------------------------------
        # Traffic manager
        # ------------------------------------------------------------------------------------------

        bus_list = self.__traffic_manager(bus)

        # ------------------------------------------------------------------------------------------
        # CNetwork Egress
        # ------------------------------------------------------------------------------------------

        self.__egress_process(bus_list)

        # Throw out any packets dropped in egress.
        bus_list = filter(
            lambda bus: not bus.metadata["standard_metadata"]["egress_spec"].is_max_val(),
            bus_list,
        )

        # ------------------------------------------------------------------------------------------
        # CNetwork Deparser
        # ------------------------------------------------------------------------------------------

        bus_packet_out_list += [(bus, self.__deparser.process(bus.packet)) for bus in bus_list]

        # ------------------------------------------------------------------------------------------
        # Emit
        # ------------------------------------------------------------------------------------------

        return self.__emit(bus_packet_out_list)


@dataclass
class V1QuantumPortMeta:
    """V1Quantum port metadata."""

    pathway: int
    standard_metadata: dict
    qdevice_metadata: dict


class V1QuantumRuntimeAbc(V1ModelRuntimeAbc):
    """The abstract base class for a V1Quantum runtime."""
    # Currently no different to v1model.


class V1QuantumExtern(V1ModelExtern):
    """The V1Quantum extern functionality class.

    Parameters
    ----------
    program : dict
        The P4 program in BM JSON format.

    """

    def __init__(self, program):
        super().__init__(program)
        # Currently no different to v1model.

    @staticmethod
    def division32(quotient, remainder, dividend, divisor):
        """Divide a 32-bit dividend by a 32-bit divisor.

        Parameters
        ----------
        quotient : `int`
            The quotient of the division.
        remainder : `int`
            The remainder of the division.
        dividend : `int`
            The value to divide.
        divisor : `int`
            The value to divide by.
        """
        quotient.val = int(dividend) // int(divisor)
        remainder.val = int(dividend) % int(divisor)


class V1QuantumProcess(Process):
    """The V1Model process.

    Parameters
    ----------
    name : `str`
        The process name.
    program : `dict`
        The program to execute in the BM format.
    packet_io : `pyp4.PacketIO`
        External packet representation type.

    """

    def __init__(self, name, program, packet_io=PacketIO.BINARY):
        extern = V1QuantumExtern(program)
        super().__init__(name, program, packet_io, extern)

    @staticmethod
    def _validate_program(program):
        Process._validate_program_pipeline(
            program, ["parser"], ["ingress", "qdevice", "egress"], ["deparser"],
        )
