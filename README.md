# High Temperature Heat Pumps in Local and District Heating Systems (HTWP)

Technology perspectives for short and medium term use in multivalent systems

# Overview

This repository contains additional information and data relating to the research project *HTWP* from the authors  M. Fritz, J. Freißmann and I. Tuschy. It serves to allow for reproduction of the obtained results.

# The research project

The research project was funded by the [*Gesellschaft für Energie und Klimaschutz Schleswig-Holstein* (EKSH)](https://www.eksh.org/) as part of the [*HWT Energie und Klimaschutz*](https://www.eksh.org/projekte/hwt-energie-klimaschutz) programme. [*ARCOTS Industriekälte AG*](https://www.arctos-ag.com/home/) served as the industry partner. The authors are greatful for the support from both partners.

# Description of contents

## Heat Pump Models

This folder contains the heat pump models used to generate characteristics for the combined investment and dispatch optimization. On the main level the `HeatPumpBase` class serves as the blueprint for all heat pump models. The `HeatPumpSimple` and `HeatPumpPC` classes inherit from the base class and implement all necessary methods.
In addition to that, this directory contains an input and an output folder.

### Input

All necessary input files of the analyzed heat pumps are placed in this folder. Additionally, the `'CEPCI.json'` stores cost values of the *Chemical Engineering Plant Cost Index*.

### Output

The `'output'` folder is empty by default, but will contain output generated by the heat pump models, such as states diagrams, partload and logging data.

## Optimization

This folder contains the files for carrying out the combined investment and dispatch optimization as well as for the dispatch optimization. This requires auxiliary files such as those for the economic functions and helpers. It also contains a postprocessing file for processing the results. In addition to control files, the folders for the various district heating systems (primary network, sub network, and 4GDH network) are also stored.

### Input

The `'input'` folder contains the necessary input data for the combined investment and dispatch optimization. Generally, this includes a JSON file of the constant parameters (no variation throughout the observed period) and a CSV file of the time dependent data.

### Output

This folder serves as a container for the output data of the combined investment and dispatch optimization. For each setup, there are the unit commitment time series, as well as key parameters and unit cost. Additionally, the results are visualized in plots, that allow an even more detailed analysis than provided in the paper.

# Reproduction

To achieve reproducible results, the necessary dependencies are saved in the `requirements.txt` file. In a clean environment from the root directory the installation from this file should allow the full reproduction of the results. This steps could look like this:

```
conda create -n my_new_env python=3.10
```

```
conda activate my_new_env
```

```
python -m pip install -r requirements.txt
```
