import argparse
from collections import defaultdict

import matplotlib.pyplot as plt
import netsquid as ns
import numpy as np

from analysis.results import collect_results, calculate_request_cdf, MARKERS, COLOURS


def plot_results(results):
    fig, axis = plt.subplots(3)

    throughput_top = 600
    latency_top = 0.100
    bsm_unit_marker = {}
    bsm_unit_colour = {}

    intervals = sorted(results.keys(), reverse=False)
    rates = list(map(lambda i: 1 / (i / ns.SECOND), intervals))
    throughput_mean = defaultdict(list)
    throughput_stdev = defaultdict(list)
    latency_intervals = defaultdict(list)
    latency_mean = defaultdict(list)

    for interval in intervals:
        for n in sorted(results[interval].keys()):
            throughput_mean[n].append(results[interval][n].throughput.mean)
            throughput_stdev[n].append(results[interval][n].throughput.stdev)
            if (interval == 2_857_143) and (n == 5):
                # Manually skip this point as it's just a bit above capacity so it appears
                # converged, but is unlikely to be reliable.
                continue
            if results[interval][n].latency.mean <= latency_top:
                latency_intervals[n].append(interval)
                latency_mean[n].append(results[interval][n].latency.mean)

    marker_count = 0
    colour_count=0
    for n in sorted(throughput_mean.keys(), reverse=False):
        axis[0].errorbar(
            rates, throughput_mean[n],
            marker=MARKERS[marker_count], color=COLOURS[colour_count],
            label=str(n),
        )
        axis[0].set_xlim(left=0, right=650)
        axis[0].set_yticks(range(0, throughput_top+1, 100))
        axis[0].set_ylim(bottom=0, top=throughput_top)

        bsm_unit_marker[n] = MARKERS[marker_count]
        bsm_unit_colour[n] = COLOURS[colour_count]
        marker_count += 1
        colour_count = marker_count % len(COLOURS)

    cdf_interval = 2_500_000  # 400
    cdf_rate = 1 / (cdf_interval / ns.SECOND)
    axis[1].axvline(x=cdf_rate, color="silver", linestyle="dashed")

    for n in sorted(latency_mean.keys(), reverse=False):
        latency_rates = list(map(lambda i: 1 / (i / ns.SECOND), latency_intervals[n]))

        if latency_rates:
            axis[1].plot(
                latency_rates, latency_mean[n],
                marker=bsm_unit_marker[n], color=bsm_unit_colour[n],
            )
            axis[1].set_xlim(left=0, right=650)
            axis[1].set_yticks(list(map(lambda y: y / 100, range(0, 11, 2))))
            axis[1].set_ylim(bottom=0, top=latency_top)

            if cdf_interval in latency_intervals[n]:
                bin_times = list(range(1, 11))
                bin_times = list(map(lambda t: t / 100, bin_times))
                cdf = calculate_request_cdf(results, cdf_interval, n, bin_times)
                axis[2].plot(
                    bin_times, cdf,
                    marker=bsm_unit_marker[n], color=bsm_unit_colour[n],
                )
                axis[2].set_xlim(left=0, right=(bin_times[-1]+0.01))
                axis[2].set_ylim(bottom=-0.1, top=1.1)


    return fig, axis


def label(fig, axis):
    axis[0].set_ylabel("Throughput (/s)")
    axis[0].set_xlabel("Request rate (/s)")

    axis[1].set_ylabel("Latency (s)")
    axis[1].set_xlabel("Request rate (/s)")

    axis[2].set_ylabel("Completion CDF")
    axis[2].set_xlabel("Latency (s)")


def show(fig, axis):
    fig.legend()
    plt.show()


def save(fig, axis):
    axis[0].text(-0.145, 0.975, "(a)", fontweight="bold", transform=axis[0].transAxes)
    axis[1].text(-0.155, 0.975, "(b)", fontweight="bold", transform=axis[1].transAxes)
    axis[2].text(-0.155, 0.975, "(c)", fontweight="bold", transform=axis[2].transAxes)

    fig.legend(bbox_to_anchor=(0.6, 0),loc="lower center", ncol=4)
    fig.text(0.1, 0.025, "Number of\nBSM units")

    plt.tight_layout(h_pad=-1, rect=(-0.01, 0.025, 1.01, 1.03))
    fig.set_size_inches(5, 7)
    fig.savefig("./analysis/figs/request_rate.pdf", dpi=300)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    results = collect_results("./results", (1_000_000_000, 2_000_000_000))
    fig, axis = plot_results(results)
    label(fig, axis)
    if args.show:
        show(fig, axis)
    else:
        save(fig, axis)
