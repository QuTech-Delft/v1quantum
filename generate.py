"""Generate scenario files."""

import os
import shutil
import yaml

from netsquid_netrunner import generators


CTL_PORT = 0x200


def experiment_topology(network: generators.network.Topology):
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


def generate_network(config_dir, scenario_path):
    """Generate the network configuration file.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_path : `str`
        The path for scenario for which to generate the demand.

    """
    topology = generators.network.Topology(
        base_file=os.path.join(config_dir, "network_base.yml"),
        network_config_file=os.path.join(scenario_path, "network.yml"),
    )
    experiment_topology(topology)
    topology.generate()


def generate_demand(config_dir, scenario_path):
    """Generate the demand matrix.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_path : `str`
        The path for scenario for which to generate the demand.

    """
    with open(os.path.join(scenario_path, "network.yml"), encoding="utf-8") as network_config_file:
        network_config = yaml.safe_load(network_config_file)
    generators.demand.generate(
        base_file=os.path.join(config_dir, "demand_base.yml"),
        demand_file=os.path.join(scenario_path, "demand.yml"),
        network_config=network_config,
    )


def generate_scenarios(config_dir, scenario_dir):
    """Generate scenario files.

    Parameters
    ----------
    config_dir : `str`
        The directory with base configuration.
    scenario_dir : `str`
        The root directory for scenario files.

    """
    try:
        shutil.rmtree(scenario_dir)
    except FileNotFoundError:
        pass
    os.makedirs(scenario_dir)

    # Set up the path for this scenario.
    scenario_path = os.path.join(scenario_dir, "scenario-0")
    os.mkdir(scenario_path)

    # Generate network and demand config files first.
    generate_network(config_dir, scenario_path)
    generate_demand(config_dir, scenario_path)

    # Create scenario dict
    scenario = {
        "config_path": scenario_path,
        "type_config_file": os.path.relpath(
            os.path.join(config_dir, "type.yml"),
            scenario_path,
        ),
        "network_config_file": "network.yml",
        "protocol_config_file": os.path.relpath(
            os.path.join(config_dir, "protocol.yml"),
            scenario_path,
        ),
        "demand_config_file": "demand.yml",
    }

    # And dump the scenario file
    scenario_filepath = os.path.join(scenario_path, "scenario.yml")
    with open(scenario_filepath, "w", encoding="utf-8") as scenario_file:
        yaml.dump(scenario, scenario_file, sort_keys=False)


if __name__ == "__main__":
    ROOT_DIR = "./"
    generate_scenarios(
        config_dir=os.path.join(ROOT_DIR, "config"),
        scenario_dir=os.path.join(ROOT_DIR, "scenario"),
    )
