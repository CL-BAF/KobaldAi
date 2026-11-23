"""Figure generation (matplotlib, non-interactive Agg backend)."""

from __future__ import annotations

from pathlib import Path

__all__ = ["plot_against_reference"]


def plot_against_reference(
    path: Path,
    time: tuple[float, ...],
    series: dict[str, tuple[tuple[float, ...], tuple[float, ...], str]],
    title: str,
) -> None:
    """Plot numerical vs reference series and their absolute error.

    ``series`` maps a name to ``(numerical, reference, unit)``.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    t = np.asarray(time)
    fig, axes = plt.subplots(len(series), 2, figsize=(11, 3.2 * len(series)), squeeze=False)
    for row, (name, (numerical, reference, unit)) in enumerate(series.items()):
        num, ref = np.asarray(numerical), np.asarray(reference)
        value_ax, error_ax = axes[row]
        value_ax.plot(t, ref, color="#1f4e79", linewidth=2.2, label="closed-form reference")
        value_ax.plot(t, num, color="#e07b00", linewidth=1.0, linestyle="--", label="engine output")
        value_ax.set_ylabel(f"{name} [{unit}]")
        value_ax.legend(loc="upper right", frameon=False)
        # Exact zeros (e.g. the initial condition) are floored at machine epsilon
        # times the signal scale so the log axis shows the meaningful error range.
        floor = float(np.finfo(float).eps) * max(float(np.max(np.abs(ref))), 1e-300)
        error = np.maximum(np.abs(num - ref), floor)
        error_ax.semilogy(t, error, color="#7a1f1f", linewidth=1.0)
        error_ax.set_ylabel(f"|error| [{unit}] (floor: eps x scale)")
        for ax in (value_ax, error_ax):
            ax.grid(alpha=0.3)
            ax.set_xlabel("time [s]")
    fig.suptitle(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, metadata={"Software": None})
    plt.close(fig)
