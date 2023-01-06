import argparse
import enum
import importlib
import os

from netsquid_netrunner.experiment import Experiment


class ExperimentType(str, enum.Enum):
    QRX = "qrx"
    HUB = "hub"


if __name__ == "__main__":
        __parser = argparse.ArgumentParser(description="Run and iterate the hub experiment.")

        __parser.add_argument(
            "--experiment-type",
            type=str.lower,
            choices=[str.lower(t) for t in ExperimentType],
            default="qrx",
            help="experiment type",
        )
        __parser.add_argument(
            "--iterations",
            type=int,
            default=1,
            help="number of iterations"
        )

        __args = __parser.parse_args()

        generate_module = importlib.import_module(f"experiments.{__args.experiment_type}.generate")

        root_dir = f"experiments/{__args.experiment_type}"
        scenarios_dir = os.path.join(root_dir, "scenarios")
        results_dir = os.path.join(root_dir, "results")

        for _ in range(__args.iterations):
            generate_module.generate_experiment(scenarios_dir)
            Experiment(scenarios_dir, results_dir).run()
