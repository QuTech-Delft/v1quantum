import os
import shutil


def trim_results(results_root):
    for scenario in os.listdir(results_root):
        iterations = sorted(os.listdir(os.path.join(results_root, scenario)))
        for iter in iterations[1:]:
            shutil.rmtree(os.path.join(results_root, scenario, iter))

def clean_results(results_root):
    for scenario in os.listdir(results_root):
        for iteration in os.listdir(os.path.join(results_root, scenario)):
            if not os.path.isfile(os.path.join(results_root, scenario, iteration, "results.json")):
                shutil.rmtree(os.path.join(results_root, scenario, iteration))
        if not os.listdir(os.path.join(results_root, scenario)):
            shutil.rmtree(os.path.join(results_root, scenario))

def completed_scenarios(results_root):
    scenarios = set()
    for scenario in os.listdir(results_root):
        assert os.listdir(os.path.join(results_root, scenario))
        for iteration in os.listdir(os.path.join(results_root, scenario)):
            assert os.path.isfile(os.path.join(results_root, scenario, iteration, "results.json"))
        scenarios.add(scenario)
    return scenarios

def clean_scenarios(scenario_root, scenarios):
    for scenario in os.listdir(scenario_root):
        if scenario in scenarios:
            shutil.rmtree(os.path.join(scenario_root, scenario))

if __name__ == "__main__":
    clean_results("./results")
    trim_results("./results")
    # clean_scenarios("./scenario", completed_scenarios("./results"))
