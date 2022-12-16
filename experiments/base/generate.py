"""Generate scenario files."""

from netsquid_netrunner.components.controller import Controller
from netsquid_netrunner.components.connections import ClassicalConnection, QuantumConnection
from netsquid_netrunner.generators.network import NetworkBase, LinkPort
from netsquid_netrunner.generators.protocol import ProtocolGenerator
from netsquid_netrunner.generators.type import TypeGenerator

from v1quantum.components.qnode import QNode
from v1quantum.components.heralding_station import HeraldingStation


CTL_PORT = 0x200


def connect_quantum(network, link_port_1, link_port_2):
    for link in ["", "cl-", "qu-"]:
        connect = network.connect_quantum if (link == "qu-") else network.connect_classical
        connect(
            LinkPort(comp=link_port_1.comp, port=f"{link}{link_port_1.port}"),
            LinkPort(comp=link_port_2.comp, port=f"{link}{link_port_2.port}"),
        )


def network_base():
    base = NetworkBase()
    base.update_heralding_station({
        "num_bsm_units": 1,
        "bsm_properties": {
            "p_dark": 5.0e-7,
            "det_eff": 0.8,
            "visibility": 0.9,
        }
    })
    base.update_host({"nqubits": 1})
    base.update_repeater({"nqubits": 2})
    base.update_router({"nqubits": None})
    classical_properties = {
        "length": 5,
        "fibre_delay_model": {"c": 206753.41931034482},
    }
    base.update_classical_connection(classical_properties)
    base.update_quantum_connection({
        **classical_properties,
        "fibre_loss_model": {"p_loss_init": 0.0, "p_loss_length": 0.5},
    })
    return base


def generate_protocol():
    protocol = ProtocolGenerator()

    protocol.set_controller_control_plane("v1quantum.protocol.control_plane.controller.Controller")

    protocol.set_router_control_plane("v1quantum.protocol.control_plane.agent.Agent")
    protocol.set_router_data_plane(
        "v1quantum.protocol.data_plane.p4.P4DataPlane",
        program_file_name="./v1quantum/protocol/data_plane/p4/q-int-node.json",
    )

    protocol.set_repeater_control_plane("v1quantum.protocol.control_plane.agent.Agent")
    protocol.set_repeater_data_plane(
        "v1quantum.protocol.data_plane.p4.P4DataPlane",
        program_file_name="./v1quantum/protocol/data_plane/p4/q-int-node.json",
    )

    protocol.set_heralding_station_control_plane("v1quantum.protocol.control_plane.agent.Agent")
    protocol.set_heralding_station_data_plane(
        "v1quantum.protocol.data_plane.p4.P4DataPlane",
        program_file_name="./v1quantum/protocol/data_plane/p4/heralding_station.json",
    )

    protocol.set_host_user_space("v1quantum.protocol.control_plane.host.EntangleAndMeasure")
    protocol.set_host_data_plane(
        "v1quantum.protocol.data_plane.p4.P4DataPlane",
        program_file_name="./v1quantum/protocol/data_plane/p4/q-end-node.json",
    )
    return protocol


def generate_type():
    type = TypeGenerator()
    type.set_controller(Controller)
    type.set_router(QNode)
    type.set_repeater(QNode)
    type.set_heralding_station(HeraldingStation)
    type.set_host(QNode)
    type.set_classical_connection(ClassicalConnection)
    type.set_quantum_connection(QuantumConnection)
    return type
