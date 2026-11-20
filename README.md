# Energy-optimal allocation of multiple workloads on CPU–FPGA nodes: code and data

This repository accompanies the paper

> P. Palazzari, M. Faltelli, M. Fois, F. Iannone, P. Tommasino,
> *Energy-Optimal Allocation of Multiple Workloads on CPU–FPGA Nodes*,
> submitted to IEEE Transactions on Parallel and Distributed Systems.

It contains the orchestrator that runs the allocations, the workload descriptors,
the scripts of every measurement campaign, the analysis and model scripts, and the
raw power logs of all the campaigns reported in the paper.

## Contents

| Folder | Content |
|---|---|
| `orchestrator/` | `run_multi.py` and its variants (pinning, several FPGAs), the CPU workers, the power logger (`power_logger.py`), the analysis of power logs (`analyze_power.py`), and the workload descriptors (`workloads*.json`) |
| `campaigns/` | one shell script per campaign: checks, idle windows, interleaved runs, logging |
| `analysis/model/` | the energy model with and without interference (`sim.py`), exhaustive search of the optimum, sensitivity to the idle power, reconfiguration check, Fig. 2 |
| `analysis/scripts/` | analysis of the individual campaigns (interference matrix, footprints, reconfiguration, random allocations, equal-work allocations) |
| `tools/` | `collect.sh` (fills `orchestrator/` and `data/raw/` from the framework), `campaigns.tsv` (map from campaigns to raw folders and to the paper), `files.txt` (the programs used in this work), patches used to create the pinned and multi-FPGA variants of the orchestrator |
| `data/raw/<campaign>/` | raw data, one folder per session (see below) |
| `data/derived/` | allocations and per-run results of the random-allocation campaign |

The comments in the scripts are in Italian; the code, the file formats and this
README are what is needed to reproduce the results.

## Campaigns

`tools/campaigns.tsv` maps every campaign to the sections, tables and figures of the
paper. In short:

| Campaign | Paper | Raw folders |
|---|---|---|
| per-unit parameters | Table 4 | `parameters/` |
| reconfiguration | $t_\mathrm{cfg}$, $E_\mathrm{cfg}$ | `reconfiguration/` |
| footprint of the FPGA runtime | Table S2 | `footprint/` |
| interference matrix | Table 9 | `interference/` |
| A, three workloads | Sec. 6.1.1 | `A/` |
| B, four workloads, two regimes | Sec. 6.1.2 | `B/`, `juxtaposed/` |
| equal-work and random allocations | Sec. 6.3, Fig. 2, Table S4 | `equal_work/`, `random/` |
| C, without pinning | Sec. 6.4.1 | `C/` |
| D, with pinning | Sec. 6.4.2, Table S3 | `D/` |
| E, two FPGAs | Sec. 6.5 | `E/` (one folder per node) |

## Raw data format

Each session folder contains:

- `*_power_*.log.gz`: node power read from the BMC
  via IPMI, in-band, about once per second. Tab-separated columns: Unix time (s),
  node power (W), ISO time (UTC), BMC time stamp.
- `runs.tsv`: one line per run, with tag, allocation and start/end times.
- `<tag>_timeline.json`: start and end of every workload on every device class,
  the allocation and the makespan.
- `<tag>.out`: output of the orchestrator for that run.
- `idle_windows.tsv`: start and end (Unix time) of the dedicated idle windows used to
  measure $P_\mathrm{idle}$.
- `info.txt`: node, governor, XRT and kernel versions, power-log file.
- `ventole.tsv` (recent campaigns only): every 60 s, Unix time, fan power (W), minimum
  and maximum fan speed (RPM), inlet air temperature (°C).

The energy of a run is the trapezoidal integral of the power samples between its
start and end:

```
python3 orchestrator/analyze_power.py <power log> <runs.tsv> --csv risultati.csv
```

(`analyze_power.py` reads compressed logs after `gunzip`.)

## Platform

Two identical nodes, each with 2 × Intel Xeon Gold 6342 (48 cores) and
2 × AMD Alveo U55C; XRT 2.19, Vitis 2023.1, CPU governor `performance`.
The FPGA kernels themselves are not part of this repository.

## License

The code (orchestrator, campaign scripts, analysis and model scripts) is released
under the license in the `LICENSE` file. The data (`data/raw/` and `data/derived/`)
are released under the Creative Commons Attribution 4.0 International license
(CC BY 4.0, https://creativecommons.org/licenses/by/4.0/): they can be shared and
adapted, provided that the paper above is cited.
