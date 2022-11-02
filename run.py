import datetime

from netsquid_netrunner.runall import run_all

from generate import generate_experiment

if __name__ == "__main__":
    for i in range(10):
        print(f"Runall iteration {i} at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        generate_experiment(
            config_dir="./config",
            scenario_dir="./scenario",
            experiment_type="hub",
        )
        run_all(
            scenario_root_path="./scenario",
            results_root_path="./results",
        )
