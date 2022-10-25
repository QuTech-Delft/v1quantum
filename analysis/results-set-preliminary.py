from collections import defaultdict
import dataclasses
import json
import os
import re

import matplotlib.pyplot as plt
import netsquid as ns
import numpy as np


@dataclasses.dataclass
class Result:
    interval: int
    bsm_units: int
    results_file: str
    throughput: float
    latency: float


def get_throughput_and_latency(result_file):
    with open(result_file, encoding="utf-8") as json_file:
        results = json.load(json_file)

    t0 = 1_000_000_000
    t1 = 9_000_000_000
    dt = t1 - t0

    app_results = results["app_results"]
    completed_requests = 0
    latency_sum = 0.0
    for app_result in app_results:
        if app_result["node0"] is not None:
            assert app_result["node1"] is not None
            request_time = app_result["node0"]["request_time"]
            start_time = app_result["node0"]["start_time"]
            end_time = app_result["node0"]["end_time"]
            if (start_time >= t0) and (end_time <= t1):
                completed_requests += 1
                latency_sum += (start_time - request_time)

    return (completed_requests / (dt / ns.SECOND)), (latency_sum / completed_requests)


def collect_results(results_root):
    results = defaultdict(dict)
    spokes = None
    for result_dir in os.listdir(results_root):
        parsed = re.search(
            "scenario---spokes-(\d+)---interval-(\d+)---bsm-units-(\d+)",
            result_dir,
        ).groups()
        if spokes is None:
            spokes = int(parsed[0])
        else:
            assert spokes == int(parsed[0])
        interval = int(parsed[1])
        bsm_units = int(parsed[2])


        result_iterations = os.listdir(os.path.join(results_root, result_dir))
        result_iterations.sort()
        result_file = os.path.join(results_root, result_dir, result_iterations[-1], "results.json")

        throughput, latency = get_throughput_and_latency(result_file)

        results[interval][bsm_units] = Result(
            interval=interval,
            bsm_units=bsm_units,
            results_file=result_file,
            throughput=throughput,
            latency=latency,
        )

    return results


def plot_results(results):
    fig, axis = plt.subplots(4)
    del results[1000000]
    del results[2000000]
    del results[4000000]
    del results[8000000]

    for interval in sorted(results.keys(), reverse=True):
        bsm_units = np.array(sorted(results[interval].keys()))
        throughput = [results[interval][n].throughput for n in bsm_units]
        latency = [results[interval][n].latency for n in bsm_units]
        axis[0].plot(bsm_units, throughput, label=str(interval / ns.SECOND))
        axis[1].plot(bsm_units, latency, label=str(interval / ns.SECOND))

    intervals = sorted(results.keys())
    throughput = defaultdict(list)
    latency = defaultdict(list)
    for interval in intervals:
        for n in sorted(results[interval].keys()):
            throughput[n].append(results[interval][n].throughput)
            latency[n].append(results[interval][n].latency)

    for n in sorted(throughput.keys()):
        axis[2].plot(list(map(lambda i: 1 / i, intervals)), throughput[n], label=str(n))

    for n in sorted(latency.keys()):
        axis[3].plot(list(map(lambda i: 1 / i, intervals)), latency[n], label=str(n))

    for ax in axis:
        ax.legend()
    plt.show()


if __name__ == "__main__":
    plot_results(collect_results("./results-set-preliminary"))
