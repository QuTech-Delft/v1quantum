"""Generate scenario files."""

import os
import shutil
from netsquid_netrunner.generators.protocol import ProtocolGenerator
from netsquid_netrunner.generators.type import TypeGenerator
import yaml

from netsquid_netrunner.generators.demand import DemandGenerator, ParameterDistribution as pd
from netsquid_netrunner.generators.network import NetworkBase, NetworkGenerator, LinkPort
import numpy.random

from experiments.base.generate import CTL_PORT, network_base, generate_protocol, generate_type


def connect_quantum(network, link_port_1, link_port_2):
    for link in ["", "cl-", "qu-"]:
        connect = network.connect_quantum if (link == "qu-") else network.connect_classical
        connect(
            LinkPort(comp=link_port_1.comp, port=f"{link}{link_port_1.port}"),
            LinkPort(comp=link_port_2.comp, port=f"{link}{link_port_2.port}"),
        )


def generate_network():
    base: NetworkBase = network_base()
    base.update_classical_connection({"length": 25})
    base.update_quantum_connection({"length": 25})
    network = NetworkGenerator(base)
    topology(network)
    return network


def topology(network):
    # -----------------------------------------
    #                                      hc0
    #                                      /
    #  ha0---qhsa---qrx---qhsi---qrp---qhsc
    #                |                     \
    #               qhsb                   hc1
    #                |
    #               hb0
    # -----------------------------------------
    network.add_controller()

    network.add_router("qrx", {"nqubits": 3})

    network.add_repeater("qrp")

    network.add_heralding_station("qhsa")
    network.add_heralding_station("qhsb")
    network.add_heralding_station("qhsc")
    network.add_heralding_station("qhsi")

    network.add_host("ha0")
    network.add_host("hb0")
    network.add_host("hc0")
    network.add_host("hc1")

    # ----------------------------------------------------------------------------------------------
    # Controller links.
    # ----------------------------------------------------------------------------------------------
    network.connect_classical(
        LinkPort(comp="controller", port="qrx"),
        LinkPort(comp="qrx", port=str(CTL_PORT)),
        properties={"length": 0},
    )

    network.connect_classical(
        LinkPort(comp="controller", port="qrp"),
        LinkPort(comp="qrp", port=str(CTL_PORT)),
        properties={"length": 50},
    )

    network.connect_classical(
        LinkPort(comp="controller", port="qhsa"),
        LinkPort(comp="qhsa", port=str(CTL_PORT)),
        properties={"length": 25},
    )
    network.connect_classical(
        LinkPort(comp="controller", port="qhsb"),
        LinkPort(comp="qhsb", port=str(CTL_PORT)),
        properties={"length": 25},
    )
    network.connect_classical(
        LinkPort(comp="controller", port="qhsi"),
        LinkPort(comp="qhsi", port=str(CTL_PORT)),
        properties={"length": 25},
    )
    network.connect_classical(
        LinkPort(comp="controller", port="qhsc"),
        LinkPort(comp="qhsc", port=str(CTL_PORT)),
        properties={"length": 75},
    )

    network.connect_classical(
        LinkPort(comp="controller", port="ha0"),
        LinkPort(comp="ha0", port=str(CTL_PORT)),
        properties={"length": 50},
    )
    network.connect_classical(
        LinkPort(comp="controller", port="hb0"),
        LinkPort(comp="hb0", port=str(CTL_PORT)),
        properties={"length": 50},
    )
    network.connect_classical(
        LinkPort(comp="controller", port="hc0"),
        LinkPort(comp="hc0", port=str(CTL_PORT)),
        properties={"length": 100},
    )
    network.connect_classical(
        LinkPort(comp="controller", port="hc1"),
        LinkPort(comp="hc1", port=str(CTL_PORT)),
        properties={"length": 100},
    )

    # ----------------------------------------------------------------------------------------------
    # Backbone link.
    # ----------------------------------------------------------------------------------------------
    connect_quantum(
        network,
        LinkPort(comp="qhsi", port=1),
        LinkPort(comp="qrx", port=1),
    )
    connect_quantum(
        network,
        LinkPort(comp="qhsi", port=2),
        LinkPort(comp="qrp", port=1),
    )

    # ----------------------------------------------------------------------------------------------
    # QRX to zones A and B.
    # ----------------------------------------------------------------------------------------------
    connect_quantum(
        network,
        LinkPort(comp="qrx", port=2),
        LinkPort(comp="qhsa", port=1),
    )
    connect_quantum(
        network,
        LinkPort(comp="qrx", port=3),
        LinkPort(comp="qhsb", port=1),
    )

    # ----------------------------------------------------------------------------------------------
    # QRP to zone C.
    # ----------------------------------------------------------------------------------------------
    connect_quantum(
        network,
        LinkPort(comp="qrp", port=2),
        LinkPort(comp="qhsc", port=1),
    )

    # ----------------------------------------------------------------------------------------------
    # Zone A.
    # ----------------------------------------------------------------------------------------------
    connect_quantum(
        network,
        LinkPort(comp="qhsa", port=2),
        LinkPort(comp="ha0", port=1),
    )

    # ----------------------------------------------------------------------------------------------
    # Zone B.
    # ----------------------------------------------------------------------------------------------
    connect_quantum(
        network,
        LinkPort(comp="qhsb", port=2),
        LinkPort(comp="hb0", port=1),
    )

    # ----------------------------------------------------------------------------------------------
    # Zone C.
    # ----------------------------------------------------------------------------------------------
    connect_quantum(
        network,
        LinkPort(comp="qhsc", port=2),
        LinkPort(comp="hc0", port=1),
    )
    connect_quantum(
        network,
        LinkPort(comp="qhsc", port=3),
        LinkPort(comp="hc1", port=1),
    )

    # ----------------------------------------------------------------------------------------------
    # Host-to-host.
    # ----------------------------------------------------------------------------------------------
    network.connect_classical(
        LinkPort(comp="ha0", port="hb0"),
        LinkPort(comp="hb0", port="ha0"),
        properties={"length": 100},
    )
    network.connect_classical(
        LinkPort(comp="ha0", port="hc0"),
        LinkPort(comp="hc0", port="ha0"),
        properties={"length": 150},
    )
    network.connect_classical(
        LinkPort(comp="ha0", port="hc1"),
        LinkPort(comp="hc1", port="ha0"),
        properties={"length": 150},
    )
    network.connect_classical(
        LinkPort(comp="hb0", port="hc0"),
        LinkPort(comp="hc0", port="hb0"),
        properties={"length": 150},
    )
    network.connect_classical(
        LinkPort(comp="hb0", port="hc1"),
        LinkPort(comp="hc1", port="hb0"),
        properties={"length": 150},
    )
    network.connect_classical(
        LinkPort(comp="hc0", port="hc1"),
        LinkPort(comp="hc1", port="hc0"),
        properties={"length": 50},
    )


def generate_demand():
    demand = DemandGenerator()
    demand.set_number_of_requests(3)
    demand.set_request_parameter("num_pairs", pd.normal(int, 10, 0))
    demand.set_request_time_delta_distribution(pd.exponential(int, 10_000_000))
    return demand


def generate_scenario(scenario_path):
    scenario = {
        "config_path": scenario_path,
        "demand_config_file": "demand.yml",
        "network_config_file": "network.yml",
        "protocol_config_file": "protocol.yml",
        "type_config_file": "type.yml",
    }

    # And dump the scenario file
    scenario_filepath = os.path.join(scenario_path, "scenario.yml")
    with open(scenario_filepath, "w", encoding="utf-8") as scenario_file:
        yaml.dump(scenario, scenario_file, sort_keys=False)


def generate_experiment(scenario_dir):
    try:
        shutil.rmtree(scenario_dir)
    except FileNotFoundError:
        pass
    os.makedirs(scenario_dir)

    # Set up the path for this scenario.
    scenario_path = os.path.join(scenario_dir, "scenario-0")
    os.mkdir(scenario_path)

    demand: DemandGenerator = generate_demand()
    network: NetworkGenerator = generate_network()
    protocol: ProtocolGenerator = generate_protocol()
    type: TypeGenerator = generate_type()

    demand.generate(
        demand_file=os.path.join(scenario_path, "demand.yml"),
        rng=numpy.random.default_rng(),
        hosts=["ha0", "hb0", "hc0", "hc1"],
    )
    network.generate(os.path.join(scenario_path, "network.yml"))
    protocol.generate(os.path.join(scenario_path, "protocol.yml"))
    type.generate(os.path.join(scenario_path, "type.yml"))

    generate_scenario(scenario_path)


if __name__ == "__main__":
    ROOT_DIR = "./experiments/qrx"
    generate_experiment(os.path.join(ROOT_DIR, "scenarios"))
