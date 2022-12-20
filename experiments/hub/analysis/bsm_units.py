import argparse
import os

import matplotlib.pyplot as plt
import numpy as np

from experiments.hub.analysis.results import (
    collect_results,
    calculate_request_cdf,
    MARKERS,
    COLOURS,
)


def plot_results(results):
    fig, axis = plt.subplots(3)

    throughput_top = 600
    latency_top = 0.100
    rate_marker = {}
    rate_colour = {}

    marker_count = 0
    colour_count=0
    for rate in sorted(results.keys(), reverse=False):
        bsm_units = np.array(sorted(results[rate].keys()))

        throughput_mean = [results[rate][n].throughput.mean for n in bsm_units]

        axis[0].plot(
            bsm_units, throughput_mean,
            marker=MARKERS[marker_count], color=COLOURS[colour_count],
            linestyle="dashed",
            label=rate,
        )
        axis[0].set_yticks(range(0, throughput_top+1, 100))
        axis[0].set_ylim(bottom=0, top=throughput_top)

        rate_marker[rate] = MARKERS[marker_count]
        rate_colour[rate] = COLOURS[colour_count]
        marker_count += 1
        colour_count = marker_count % len(COLOURS)

    cdf_bsm_units = 6
    axis[1].axvline(x=cdf_bsm_units, color="silver", linestyle="dashed")

    for rate in sorted(results.keys(), reverse=False):

        latency_bsm_units = []
        latency_mean = []
        latency_stdev = []
        latency_low = []
        latency_high = []

        for n in bsm_units:
            if (rate == 350) and (n == 5):
                # Manually skip this point as it's just a bit above capacity so it appears
                # converged, but is unlikely to be reliable.
                continue
            if results[rate][n].latency.mean <= latency_top:
                latency_bsm_units.append(n)
                latency_mean.append(results[rate][n].latency.mean)
                latency_stdev.append(results[rate][n].latency.stdev)
                latency_low.append(results[rate][n].latency.mean -
                                   results[rate][n].latency.low)
                latency_high.append(results[rate][n].latency.high -
                                    results[rate][n].latency.mean)


        if latency_bsm_units:
            axis[1].plot(
                latency_bsm_units, latency_mean,
                marker=rate_marker[rate], color=rate_colour[rate],
                linestyle="dashed",
            )
            axis[1].set_yticks(list(map(lambda y: y / 100, range(0, 11, 2))))
            axis[1].set_ylim(bottom=0, top=latency_top)

            if cdf_bsm_units in latency_bsm_units:
                bin_times = list(range(1, 11))
                bin_times = list(map(lambda t: t / 100, bin_times))
                cdf = calculate_request_cdf(results, rate, cdf_bsm_units, bin_times)
                axis[2].plot(
                    bin_times, cdf,
                    marker=rate_marker[rate], color=rate_colour[rate],
                )
                axis[2].set_xlim(left=0, right=(bin_times[-1]+0.01))
                axis[2].set_ylim(bottom=-0.1, top=1.1)


    return fig, axis


def label(fig, axis):
    axis[0].set_ylabel("Throughput (/s)")
    axis[0].set_xlabel("Number of BSM units")

    axis[1].set_ylabel("Latency (s)")
    axis[1].set_xlabel("Number of BSM units")

    axis[2].set_ylabel("Completion CDF")
    axis[2].set_xlabel("Latency (s)")


def show(fig, axis):
    fig.legend()
    plt.show()


def save(fig, axis):
    axis[0].text(-0.145, 0.975, "(a)", fontweight="bold", transform=axis[0].transAxes)
    axis[1].text(-0.155, 0.975, "(b)", fontweight="bold", transform=axis[1].transAxes)
    axis[2].text(-0.155, 0.975, "(c)", fontweight="bold", transform=axis[2].transAxes)

    fig.legend(bbox_to_anchor=(0.58, 0),loc="lower center", ncol=4)
    fig.text(0.06, 0.04, "Request\nrate (/s)")

    plt.tight_layout(h_pad=-1, rect=(-0.01, 0.055, 1.01, 1.03))
    fig.set_size_inches(5, 7)
    os.makedirs("./experiments/hub/analysis/figs", exist_ok=True)
    fig.savefig("./experiments/hub/analysis/figs/bsm_units.pdf", dpi=300)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    results = collect_results("./experiments/hub/results", (1_000_000_000, 2_000_000_000))
    fig, axis = plot_results(results)
    label(fig, axis)
    if args.show:
        show(fig, axis)
    else:
        save(fig, axis)
