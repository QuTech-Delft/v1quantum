"""Generate scenario files."""

import os
import shutil
import tempfile
from netsquid_netrunner.generators.protocol import ProtocolGenerator
from netsquid_netrunner.generators.type import TypeGenerator
import yaml

from netsquid_netrunner.generators.demand import DemandGenerator, ParameterDistribution as pd
from netsquid_netrunner.generators.network import NetworkBase, NetworkGenerator, LinkPort
from netsquid_netrunner.generators.netsquid import NetsquidGenerator
import numpy.random

from experiments.base.generate import (
    CTL_PORT,
    connect_quantum,
    generate_protocol,
    generate_type,
    network_base,
)


def generate_network(num_bsm_units, num_spokes):
    base: NetworkBase = network_base()
    network = NetworkGenerator(base)
    topology(network, num_bsm_units, num_spokes)
    return network


def topology(network: NetworkGenerator, num_bsm_units, num_spokes):
    network.add_controller()

    network.add_heralding_station("qhs", {"num_bsm_units": num_bsm_units})

    network.connect_classical(
        LinkPort(comp="controller", port="qhs"),
        LinkPort(comp="qhs", port=str(CTL_PORT)),
        properties={"length": 0},
    )

    for spoke in range(1, num_spokes+1):
        network.add_host(f"h{spoke}")

        connect_quantum(
            network,
            LinkPort(comp="qhs", port=f"{spoke}"),
            LinkPort(comp=f"h{spoke}", port="1"),
        )

        network.connect_classical(
            LinkPort(comp="controller", port=f"h{spoke}"),
            LinkPort(comp=f"h{spoke}", port=str(CTL_PORT)),
        )

    for spoke in range(1, num_spokes+1):
        for spoke2 in range(spoke+1, num_spokes+1):
            network.connect_classical(
                LinkPort(comp=f"h{spoke}", port=f"h{spoke2}"),
                LinkPort(comp=f"h{spoke2}", port=f"h{spoke}"),
                properties={"length": 10},
            )



def generate_demand(time_limit, rate):
    demand = DemandGenerator()
    demand.set_requests_until(time_limit)
    demand.set_request_parameter("num_pairs", pd.normal(int, 50, 0))
    demand.set_request_time_average_frequency(rate)
    return demand


def generate_netsquid(time_limit):
    return NetsquidGenerator().set_time_limit(time_limit)


def generate_experiment(experiment_dir):
    scenario_dir = os.path.join(experiment_dir, "scenarios")

    try:
        shutil.rmtree(scenario_dir)
    except FileNotFoundError:
        pass
    os.makedirs(scenario_dir)

    TIME_LIMIT = 2 * (10 ** 9)
    BSM_UNITS = [1, 2, 3, 4, 5, 6, 7, 8]
    SPOKES = [16]
    RATES = [600, 550, 500, 450, 400, 350, 300, 250, 200, 150, 100, 50]
    RNG = numpy.random.default_rng()

    netsquid: NetsquidGenerator = generate_netsquid(TIME_LIMIT)
    protocol: ProtocolGenerator = generate_protocol()
    protocol.set_controller_control_plane(
        "v1quantum.protocol.control_plane.controller.HubController")
    type: TypeGenerator = generate_type()

    netsquid_file = os.path.join(experiment_dir, "netsquid.yml")
    protocol_file = os.path.join(experiment_dir, "protocol.yml")
    type_file = os.path.join(experiment_dir, "type.yml")

    netsquid.generate(netsquid_file)
    protocol.generate(protocol_file)
    type.generate(type_file)

    for num_spokes in SPOKES:
        for rate in RATES:

            demand: DemandGenerator = generate_demand(TIME_LIMIT, rate)
            demand_file = tempfile.NamedTemporaryFile(mode="w").name
            demand.generate(
                demand_file=demand_file,
                rng=RNG,
                hosts=[f"h{spoke}" for spoke in range(1, num_spokes+1)],
            )

            for num_bsm_units in BSM_UNITS:
                scenario_path = os.path.join(
                    scenario_dir,
                    "scenario"
                    f"---spokes-{num_spokes:03}"
                    f"---rate-{rate:03}"
                    f"---bsm-units-{num_bsm_units:02}",
                )
                os.mkdir(scenario_path)

                shutil.copyfile(demand_file, os.path.join(scenario_path, "demand.yml"))

                network: NetworkGenerator = generate_network(num_bsm_units, num_spokes)
                network.generate(os.path.join(scenario_path, "network.yml"))

                scenario = {
                    "config_path": scenario_path,
                    "demand_config_file": "demand.yml",
                    "netsquid_config_file": os.path.relpath(netsquid_file, scenario_path),
                    "network_config_file": "network.yml",
                    "protocol_config_file": os.path.relpath(protocol_file, scenario_path),
                    "type_config_file": os.path.relpath(type_file, scenario_path),
                }

                # And dump the scenario file
                scenario_filepath = os.path.join(scenario_path, "scenario.yml")
                with open(scenario_filepath, "w", encoding="utf-8") as scenario_file:
                    yaml.dump(scenario, scenario_file, sort_keys=False)


if __name__ == "__main__":
    ROOT_DIR = "./experiments/hub"
    generate_experiment(ROOT_DIR)
