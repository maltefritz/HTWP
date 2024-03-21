import json
import os

import energy_system_invest
import pandas as pd
import postprocessing_invest

# %% Simulation parameters
# Possible energy_systems: 'pn', 'pn_wohp', 'sns', 'sn', 'IVgdh'
energy_systems = ['pn', 'sn', 'IVgdh']

# Possible scenarios: '19'
scenarios = ['19']

# Call of energy system functions
es_funcs = {
    'pn': energy_system_invest.primary_network_invest,
    'sn': energy_system_invest.sub_network_invest,
    'IVgdh': energy_system_invest.IVgdh_network_invest
    }

# Call of postprocessing functions
pp_funcs = {
    'pn': postprocessing_invest.primary_network_invest,
    'sn': postprocessing_invest.sub_network_invest,
    'IVgdh': postprocessing_invest.IVgdh_network_invest
    }

# Readability help
longnames = {
    'pn': 'primary_network', 'pn_wohp': 'primary_network_wohp',
    'sns': 'sub_network_simple', 'sn': 'sub_network', 'IVgdh': 'IVgdh_network'
    }

# Heat Pumps
hps = ['HeatPumpPCEconOpen_R717']
# hps = ['woHeatPump']

for es in energy_systems:
    for scn in scenarios:
        for hp in hps:
            # %% Read data
            inputpath = os.path.join(
                __file__, '..', longnames[es], 'input', es+scn
                )

            datafile = f'{inputpath}_invest_data_{hp}.csv'
            data = pd.read_csv(
                datafile, sep=';', index_col=0, parse_dates=True
                )

            paramfile = f'{inputpath}_invest_param_{hp}.json'
            with open(paramfile, 'r', encoding='utf-8') as file:
                param = json.load(file)

            for key in param:
                if 'tes' in key:
                    param[key]['op_cost_var'] = 0.01

            if es == 'sn':
                data['sub_heat_demand'] = data['heat_demand'] * 0.1
                param['sub st-tes']['cap_max'] = (
                    data['sub_heat_demand'].max() * 24
                )
                print(param['sub st-tes']['cap_max']/24)
            if es == 'IVgdh':
                param['s-tes']['cap_max'] = 1e6
                param['sol']['cap_max'] = 1e6

                param['s-tes']['Q_in'] = data['heat_demand'].max()
                param['s-tes']['Q_out'] = param['s-tes']['Q_in']
            print(json.dumps(param, indent=4))

            # %% Execute optimization
            args = [data, param]
            if es == 'pn':
                use_hp = True
                if hp == 'woHeatPump':
                    use_hp = False
                args.append(use_hp)

            results, meta_results = es_funcs[es](*args)

            if es in pp_funcs:
                args = [results, meta_results, data, param]
                if es == 'pn':
                    args.append(use_hp)
                data_all, data_caps, key_params, cost_df = pp_funcs[es](*args)

                outputpath = os.path.join(
                    __file__, '..', longnames[es], 'output', f'{es}{scn}_invest'
                    )

                capsfile = f'{outputpath}_capacities_{hp}.csv'
                data_caps.to_csv(capsfile, sep=';')

                tsfile = f'{outputpath}_timeseries_{hp}.csv'
                data_all.to_csv(tsfile, sep=';')

                keyparampath = f'{outputpath}_key_parameters_{hp}.json'
                with open(keyparampath, 'w', encoding='utf-8') as file:
                    json.dump(key_params, file, indent=4, sort_keys=True)

                cost_df.to_csv(f'{outputpath}_unit_cost_{hp}.csv', sep=';')
