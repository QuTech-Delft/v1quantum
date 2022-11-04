import argparse
import matplotlib.pyplot as plt
import netsquid as ns
import numpy as np

from analysis.results import collect_results, calculate_request_cdf, MARKERS, COLOURS


def plot_results(results):
    fig, axis = plt.subplots(3)

    throughput_top = 600
    latency_top = 0.100
    interval_marker = {}
    interval_colour = {}

    marker_count = 0
    colour_count=0
    for interval in sorted(results.keys(), reverse=True):
        bsm_units = np.array(sorted(results[interval].keys()))

        throughput_mean = [results[interval][n].throughput.mean for n in bsm_units]

        axis[0].plot(
            bsm_units, throughput_mean,
            marker=MARKERS[marker_count], color=COLOURS[colour_count],
            linestyle="dashed",
            label=int((1 / (interval / ns.SECOND)) + 0.5),
        )
        axis[0].set_yticks(range(0, throughput_top+1, 100))
        axis[0].set_ylim(bottom=0, top=throughput_top)

        interval_marker[interval] = MARKERS[marker_count]
        interval_colour[interval] = COLOURS[colour_count]
        marker_count += 1
        colour_count = marker_count % len(COLOURS)

    cdf_bsm_units = 6
    axis[1].axvline(x=cdf_bsm_units, color="silver", linestyle="dashed")

    for interval in sorted(results.keys(), reverse=True):

        latency_bsm_units = []
        latency_mean = []
        latency_stdev = []
        latency_low = []
        latency_high = []

        for n in bsm_units:
            if (interval == 2_857_143) and (n == 5):
                # Manually skip this point as it's just a bit above capacity so it appears
                # converged, but is unlikely to be reliable.
                continue
            if results[interval][n].latency.mean <= latency_top:
                latency_bsm_units.append(n)
                latency_mean.append(results[interval][n].latency.mean)
                latency_stdev.append(results[interval][n].latency.stdev)
                latency_low.append(results[interval][n].latency.mean -
                                   results[interval][n].latency.low)
                latency_high.append(results[interval][n].latency.high -
                                    results[interval][n].latency.mean)


        if latency_bsm_units:
            axis[1].plot(
                latency_bsm_units, latency_mean,
                marker=interval_marker[interval], color=interval_colour[interval],
                linestyle="dashed",
            )
            axis[1].set_yticks(list(map(lambda y: y / 100, range(0, 11, 2))))
            axis[1].set_ylim(bottom=0, top=latency_top)

            if cdf_bsm_units in latency_bsm_units:
                bin_times = list(range(1, 11))
                bin_times = list(map(lambda t: t / 100, bin_times))
                cdf = calculate_request_cdf(results, interval, cdf_bsm_units, bin_times)
                axis[2].plot(
                    bin_times, cdf,
                    marker=interval_marker[interval], color=interval_colour[interval],
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
    fig.savefig("./analysis/figs/bsm_units.png")


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
