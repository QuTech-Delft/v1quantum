"""Generate scenario files."""

import argparse
import enum
import os
import shutil
import tempfile
import yaml

from netsquid_netrunner import generators


CTL_PORT = 0x200

class ExperimentType(str, enum.Enum):
    QRX = "qrx"
    HUB = "hub"


def qrx_topology(network: generators.network.Topology):
    """Generate the experiment topology.

    Parameters
    ----------
    network : `~netsquid_netrunner.generators.network.Topology`
        The topology object which will be used to generate the network configuration file.

    """
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
    network.connect(network.Link(
        c1_name="controller", c1_port="qrx",
        c2_name="qrx", c2_port=CTL_PORT,
        connection_properties={"length": 0},
    ))

    network.connect(network.Link(
        c1_name="controller", c1_port="qrp",
        c2_name="qrp", c2_port=CTL_PORT,
        connection_properties={"length": 50},
    ))

    network.connect(network.Link(
        c1_name="controller", c1_port="qhsa",
        c2_name="qhsa", c2_port=CTL_PORT,
        connection_properties={"length": 25},
    ))
    network.connect(network.Link(
        c1_name="controller", c1_port="qhsb",
        c2_name="qhsb", c2_port=CTL_PORT,
        connection_properties={"length": 25},
    ))
    network.connect(network.Link(
        c1_name="controller", c1_port="qhsi",
        c2_name="qhsi", c2_port=CTL_PORT,
        connection_properties={"length": 25},
    ))
    network.connect(network.Link(
        c1_name="controller", c1_port="qhsc",
        c2_name="qhsc", c2_port=CTL_PORT,
        connection_properties={"length": 75},
    ))

    network.connect(network.Link(
        c1_name="controller", c1_port="ha0",
        c2_name="ha0", c2_port=CTL_PORT,
        connection_properties={"length": 50},
    ))
    network.connect(network.Link(
        c1_name="controller", c1_port="hb0",
        c2_name="hb0", c2_port=CTL_PORT,
        connection_properties={"length": 50},
    ))
    network.connect(network.Link(
        c1_name="controller", c1_port="hc0",
        c2_name="hc0", c2_port=CTL_PORT,
        connection_properties={"length": 100},
    ))
    network.connect(network.Link(
        c1_name="controller", c1_port="hc1",
        c2_name="hc1", c2_port=CTL_PORT,
        connection_properties={"length": 100},
    ))

    # ----------------------------------------------------------------------------------------------
    # Backbone link.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="qhsi", c1_port=1,
        c2_name="qrx", c2_port=1,
        quantum_link=True,
    ))
    network.connect(network.Link(
        c1_name="qhsi", c1_port=2,
        c2_name="qrp", c2_port=1,
        quantum_link=True,
    ))

    # ----------------------------------------------------------------------------------------------
    # QRX to zones A and B.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="qrx", c1_port=2,
        c2_name="qhsa", c2_port=1,
        quantum_link=True,
    ))
    network.connect(network.Link(
        c1_name="qrx", c1_port=3,
        c2_name="qhsb", c2_port=1,
        quantum_link=True,
    ))

    # ----------------------------------------------------------------------------------------------
    # QRP to zone C.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="qrp", c1_port=2,
        c2_name="qhsc", c2_port=1,
        quantum_link=True,
    ))

    # ----------------------------------------------------------------------------------------------
    # Zone A.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="qhsa", c1_port=2,
        c2_name="ha0", c2_port=1,
        quantum_link=True,
    ))

    # ----------------------------------------------------------------------------------------------
    # Zone B.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="qhsb", c1_port=2,
        c2_name="hb0", c2_port=1,
        quantum_link=True,
    ))

    # ----------------------------------------------------------------------------------------------
    # Zone C.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="qhsc", c1_port=2,
        c2_name="hc0", c2_port=1,
        quantum_link=True,
    ))
    network.connect(network.Link(
        c1_name="qhsc", c1_port=3,
        c2_name="hc1", c2_port=1,
        quantum_link=True,
    ))

    # ----------------------------------------------------------------------------------------------
    # Host-to-host.
    # ----------------------------------------------------------------------------------------------
    network.connect(network.Link(
        c1_name="ha0", c1_port="hb0",
        c2_name="hb0", c2_port="ha0",
        connection_properties={"length": 100},
    ))
    network.connect(network.Link(
        c1_name="ha0", c1_port="hc0",
        c2_name="hc0", c2_port="ha0",
        connection_properties={"length": 150},
    ))
    network.connect(network.Link(
        c1_name="ha0", c1_port="hc1",
        c2_name="hc1", c2_port="ha0",
        connection_properties={"length": 150},
    ))
    network.connect(network.Link(
        c1_name="hb0", c1_port="hc0",
        c2_name="hc0", c2_port="hb0",
        connection_properties={"length": 150},
    ))
    network.connect(network.Link(
        c1_name="hb0", c1_port="hc1",
        c2_name="hc1", c2_port="hb0",
        connection_properties={"length": 150},
    ))
    network.connect(network.Link(
        c1_name="hc0", c1_port="hc1",
        c2_name="hc1", c2_port="hc0",
        connection_properties={"length": 50},
    ))


def generate_qrx_network(config_dir, scenario_path):
    """Generate the network configuration file.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_path : `str`
        The path for scenario for which to generate the demand.

    """
    network_config_file = os.path.join(scenario_path, "network.yml")
    topology = generators.network.Topology(
        base_file=os.path.join(config_dir, "network_base.yml"),
        network_config_file=network_config_file,
    )
    qrx_topology(topology)
    topology.generate()
    return network_config_file


def generate_hub_network(config_dir, scenario_path, num_bsm_units, num_spokes):
    """Generate the network configuration file for a HUB experiment.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_path : `str`
        The path for scenario for which to generate the demand.
    num_bsm_units : `int`
        The number of BSM units at the heralding station.
    num_spokes : `int`
        The number of arms in the star topology.

    """
    network_config_file = os.path.join(scenario_path, "network.yml")
    topology = generators.network.Topology(
        base_file=os.path.join(config_dir, "network_base.yml"),
        network_config_file=network_config_file,
    )
    generators.topologies.star.main(topology, num_bsm_units, num_spokes)

    topology.add_controller()
    topology.connect(topology.Link(
        c1_name="controller", c1_port="qhs",
        c2_name="qhs", c2_port=CTL_PORT,
        connection_properties={"length": 0},
    ))
    for spoke in range(1, num_spokes+1):
        topology.connect(topology.Link(
            c1_name="controller", c1_port=f"h{spoke}",
            c2_name=f"h{spoke}", c2_port=CTL_PORT,
        ))
        for spoke2 in range(spoke+1, num_spokes+1):
            topology.connect(topology.Link(
                c1_name=f"h{spoke}", c1_port=f"h{spoke2}",
                c2_name=f"h{spoke2}", c2_port=f"h{spoke}",
                connection_properties={"length": 10},
            ))

    topology.generate()
    return network_config_file


def generate_demand(config_dir, scenario_path, demand_base_file=None):
    """Generate the demand matrix.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_path : `str`
        The path for scenario for which to generate the demand.

    """
    if demand_base_file is None:
        demand_base_file = os.path.join(config_dir, "demand_base.yml")
    with open(os.path.join(scenario_path, "network.yml"), encoding="utf-8") as network_config_file:
        network_config = yaml.safe_load(network_config_file)
    demand_file = os.path.join(scenario_path, "demand.yml")
    generators.demand.generate(
        base_file=demand_base_file,
        demand_file=demand_file,
        network_config=network_config,
    )
    return demand_file


def generate_scenario(config_dir, scenario_path, experiment_type, demand_file=None):
    """Generate the scenario file.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_path : `str`
        The path for scenario for which to generate the demand.
    experiment_type : `v1quantum.generate.ExperimentType`
        The type of experiment to generate.
    demand_file : `str`
        The path to the demand file if a non-default one should be used.

    """
    scenario = {
        "config_path": scenario_path,
        "type_config_file": os.path.relpath(
            os.path.join(config_dir, "type.yml"),
            scenario_path,
        ),
        "network_config_file": "network.yml",
        "protocol_config_file": os.path.relpath(
            os.path.join(config_dir, f"protocol_{experiment_type}.yml"),
            scenario_path,
        ),
        "demand_config_file": ("demand.yml" if demand_file is None else
                               os.path.relpath(demand_file, scenario_path)),
        "runner_config_file": "runner.yml" if experiment_type == ExperimentType.HUB else None,
    }

    # And dump the scenario file
    scenario_filepath = os.path.join(scenario_path, "scenario.yml")
    with open(scenario_filepath, "w", encoding="utf-8") as scenario_file:
        yaml.dump(scenario, scenario_file, sort_keys=False)


def generate_runner_config(scenario_path, experiment_type):
    """Generate a runall config file.

    Parameters
    ----------
    scenario_path : `str`
        The path for scenario for which to generate the runall config.
    experiment_type : `v1quantum.generate.ExperimentType`
        The type of experiment to generate.

    """
    if experiment_type == ExperimentType.HUB:
        runner_config = {
            "time_limit": 2 * (10 ** 9),
        }
        runner_config_filepath = os.path.join(scenario_path, "runner.yml")
        with open(runner_config_filepath, "w", encoding="utf-8") as yaml_file:
            yaml.dump(runner_config, yaml_file, sort_keys=False)


def generate_experiment(config_dir, scenario_dir, experiment_type):
    """Generate scenario files.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_dir : `str`
        The root directory for scenario files.
    experiment_type : `v1quantum.generate.ExperimentType`
        The type of experiment to generate.

    """
    try:
        shutil.rmtree(scenario_dir)
    except FileNotFoundError:
        pass
    os.makedirs(scenario_dir)

    if experiment_type == ExperimentType.QRX:
        # Set up the path for this scenario.
        scenario_path = os.path.join(scenario_dir, "scenario-0")
        os.mkdir(scenario_path)

        generate_qrx_network(config_dir, scenario_path)
        generate_demand(config_dir, scenario_path)
        generate_scenario(config_dir, scenario_path, experiment_type)
    else:
        assert experiment_type == ExperimentType.HUB

        BSM_UNITS = [1, 2, 3, 4, 5, 6, 7, 8]
        SPOKES = [16]
        INTERVALS = [
            1_666_667,          # 600
            1_818_182,          # 550
            2_000_000,          # 500
            2_222_222,          # 450
            2_500_000,          # 400
            2_857_143,          # 350
            3_333_333,          # 300
            4_000_000,          # 250
            5_000_000,          # 200
            6_666_667,          # 150
            10_000_000,         # 100
            20_000_000,         # 50
        ]

        for num_spokes in SPOKES:
            for interval in INTERVALS:
                with open(os.path.join(config_dir, "demand_base.yml"), encoding="utf-8") as \
                     demand_base_file:
                    demand_base = yaml.safe_load(demand_base_file)

                with tempfile.NamedTemporaryFile(mode="w") as demand_base_file:
                    demand_base["matrix"]["requests_until"] = 2 * (10 ** 9)
                    demand_base["matrix"]["start_time"]["interval"] = interval
                    yaml.dump(demand_base, demand_base_file, sort_keys=False)
                    demand_base_file.flush()

                    demand_file = None

                    for num_bsm_units in BSM_UNITS:
                        scenario_path = os.path.join(
                            scenario_dir,
                            "scenario"
                            f"---spokes-{num_spokes:03}"
                            f"---interval-{interval:010}"
                            f"---bsm-units-{num_bsm_units:02}",
                        )
                        os.mkdir(scenario_path)

                        generate_hub_network(config_dir, scenario_path, num_bsm_units, num_spokes)

                        if demand_file is None:
                            demand_file = generate_demand(
                                config_dir,
                                scenario_path,
                                demand_base_file.name,
                            )
                        else:
                            new_demand_file = os.path.join(scenario_path, "demand.yml")
                            shutil.copyfile(demand_file, new_demand_file)
                            demand_file = new_demand_file

                        generate_scenario(config_dir, scenario_path, experiment_type, demand_file)
                        generate_runner_config(scenario_path, experiment_type)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a v1quantum experiment")
    parser.add_argument(
        "--experiment-type",
        type=str.lower,
        choices=[str.lower(t) for t in ExperimentType],
        default="qrx",
        help="experiment type",
    )
    args = parser.parse_args()

    ROOT_DIR = "./"
    generate_experiment(
        config_dir=os.path.join(ROOT_DIR, "config"),
        scenario_dir=os.path.join(ROOT_DIR, "scenario"),
        experiment_type=args.experiment_type,
    )
