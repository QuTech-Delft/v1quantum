from collections import defaultdict
import dataclasses
import json
import os
import re
from typing import Dict, List, Tuple

import netsquid as ns
import numpy as np


MARKERS = [ 'o', 'v', '^', '<', '>', 's', 'p', '*', 'h', 'D', 'P', 'X' ]


COLOURS = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple",
           "tab:brown", "tab:pink", "tab:gray", "tab:olive", "tab:cyan"]


@dataclasses.dataclass
class MeasuredValue:
    mean: float
    stdev: float
    low: float = None
    high: float = None


@dataclasses.dataclass
class Request:
    request_time: float
    start_time: float
    end_time: float


@dataclasses.dataclass
class Result:
    window: Tuple[float, float]
    rate: int
    bsm_units: int
    requests: Dict[str, List[Request]]
    throughput: MeasuredValue = None
    latency: MeasuredValue = None


def filter_requests(result_file, t0, t1):
    with open(result_file, encoding="utf-8") as json_file:
        results = json.load(json_file)

    app_results = results["app_results"]
    requests = []
    for app_result in app_results:
        if app_result["host0"] is not None:
            assert app_result["host1"] is not None
            request = Request(
                request_time=app_result["host0"]["request_time"],
                start_time=app_result["host0"]["start_time"],
                end_time=app_result["host0"]["end_time"],
            )
            if (request.start_time >= t0) and (request.end_time <= t1):
                requests.append(request)

    return requests


def get_throughput_and_latency(result):
    completed = []
    latencies = []
    for requests in result.requests.values():
        completed.append(len(requests))
        for request in requests:
            latencies.append(request.start_time - request.request_time)

    dt = result.window[1] - result.window[0]
    throughput = MeasuredValue(
        mean=(np.mean(completed) / (dt / ns.SECOND)),
        stdev=(np.std(completed) / (dt / ns.SECOND)),
    )
    latency = MeasuredValue(
        mean=(np.mean(latencies) / ns.SECOND),
        stdev=(np.std(latencies) / ns.SECOND),
        low=(np.percentile(latencies, 5) / ns.SECOND),
        high=(np.percentile(latencies, 95) / ns.SECOND),
    )

    return throughput, latency


def calculate_request_cdf(results, rate, bsm_units, bin_times):
    bins = [0] * len(bin_times)

    requests = results[rate][bsm_units].requests
    total_requests = 0
    for iter_requests in requests.values():
        total_requests += len(iter_requests)
        for req in iter_requests:
            latency = (req.start_time - req.request_time) / ns.SECOND
            for i, time in enumerate(bin_times):
                if latency < time:
                    bins[i] += 1
                    break

    cdf = np.cumsum(bins)
    cdf = list(map(lambda y: y / total_requests, cdf))
    return cdf


def collect_results(results_root, window):
    results = defaultdict(dict)
    spokes = None
    for result_dir in os.listdir(results_root):
        parsed = re.search(
            "scenario---spokes-(\d+)---rate-(\d+)---bsm-units-(\d+)",
            result_dir,
        ).groups()
        if spokes is None:
            spokes = int(parsed[0])
        else:
            assert spokes == int(parsed[0])
        rate = int(parsed[1])
        bsm_units = int(parsed[2])

        results[rate][bsm_units] = Result(
            window=window,
            rate=rate,
            bsm_units=bsm_units,
            requests={},
        )

        result_iterations = os.listdir(os.path.join(results_root, result_dir))
        result_iterations.sort()

        for iteration in result_iterations:
            result_file = os.path.join(results_root, result_dir, iteration, "results.json")
            requests = filter_requests(
                result_file,
                results[rate][bsm_units].window[0],
                results[rate][bsm_units].window[1],
            )
            results[rate][bsm_units].requests[result_file] = requests

        throughput, latency = get_throughput_and_latency(results[rate][bsm_units])
        results[rate][bsm_units].throughput = throughput
        results[rate][bsm_units].latency = latency

    return results
