import json
import os

import pandas as pd

import energy_system_invest
import postprocessing_invest

# %% Simulation parameters
overwrite = True

# Energy Systems: 'pn', 'sn', 'IVgdh'
energy_systems = ['pn', 'sn', 'IVgdh']

# Scenarios:  '19', '40DG', '40GCA'
scenarios = ['19', '40DG', '40GCA']

# Heat Pumps
hps = ['HeatPumpPCEconOpen_R717', 'HeatPumpPCEconOpen_R1234ZE(Z)', 'HeatPumpSimple_R717']

# Call of energy system functions - noch vervollständigen
es_funcs = {
    'pn': energy_system_invest.primary_network_invest,
    'sn': energy_system_invest.sub_network_invest,
    'IVgdh': energy_system_invest.IVgdh_network_invest
    }

# Call of postprocessing functions- noch vervollständigen
pp_funcs = {
    'pn': postprocessing_invest.primary_network_invest,
    'sn': postprocessing_invest.sub_network_invest,
    'IVgdh': postprocessing_invest.IVgdh_network_invest
    }

# Readability help
longnames = {
    'pn': 'primary_network', 'sn': 'sub_network', 'IVgdh': 'IVgdh_network'
    }

for es in energy_systems:
    for scn in scenarios:
        for hp in hps:
            print(f'\n##### {es}{scn}: {hp} #####\n')
            if not overwrite:
                resultpath = os.path.join(
                    __file__, '..', longnames[es], 'output', es+scn,
                    f'{es}{scn}_invest_capacities_{hp}.csv'
                    )
                if os.path.exists(resultpath):
                    print(
                        'Skipping Setup since overwrite is set to `False` and '
                        + 'results already exist.'
                        )
                    continue

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

            if '40' in scn:
                changed = False

                if data['biogas_price'].mean() != 124.82:
                    data['biogas_price'] = 124.82
                    changed = True
                    print('Biogaspreis angepasst!')

                if (es != 'IVgdh') and (scn == '40DG'):
                    if data['gas_price'].mean() != 35.28:
                        data['gas_price'] = 35.28
                        changed = True
                        print('Gaspreis angepasst!')
                elif (es != 'IVgdh') and (scn == '40GCA'):
                    if data['gas_price'].mean() != 30.32:
                        data['gas_price'] = 30.32
                        changed = True
                        print('Gaspreis angepasst!')

                if changed:
                    data.to_csv(datafile, sep=';')

            if es == 'sn':
                data['sub_heat_demand'] = data['heat_demand'] * 0.1
                data.to_csv(datafile, sep=';')
                param['sub st-tes']['cap_max'] = (
                    data['sub_heat_demand'].max() * 24
                )
                print(param['sub st-tes']['cap_max']/24)
                with open(paramfile, 'w', encoding='utf-8') as file:
                    json.dump(param, file, indent=4)

            if es == 'IVgdh':
                param['s-tes']['cap_max'] = 1e6
                param['sol']['cap_max'] = 1e6

                param['s-tes']['Q_in'] = data['heat_demand'].max()
                param['s-tes']['Q_out'] = param['s-tes']['Q_in']

                with open(paramfile, 'w', encoding='utf-8') as file:
                    json.dump(param, file, indent=4)

            # %% Prepare output file structure
            rootoutputpath = os.path.join(
                __file__, '..', longnames[es], 'output', es+scn
                )
            if not os.path.exists(rootoutputpath):
                os.mkdir(rootoutputpath)
            outputpath = os.path.join(rootoutputpath, f'{es}{scn}_invest')


            # %% Execute optimization
            logpath = os.path.join(
                longnames[es], 'output', es+scn,
                f'{es}{scn}_invest_GUROBILOG_{hp}.log'
                )

            param['param']['mipgap'] = 1e-4
            param['param']['TimeLimit'] = 60*60*2
            param['param']['MIPFocus'] = 2
            param['param']['SolverLogPath'] = logpath

            print(json.dumps(param, indent=4))

            args = [data, param]
            if es == 'pn':
                use_hp = True
                if hp == 'woHeatPump':
                    use_hp = False
                args.append(use_hp)

            results, meta_results = es_funcs[es](*args)

            args = [results, meta_results, data, param]
            if es == 'pn':
                args.append(use_hp)
            data_all, data_caps, key_params, cost_df = pp_funcs[es](*args)

            capsfile = f'{outputpath}_capacities_{hp}.csv'
            data_caps.to_csv(capsfile, sep=';')

            tsfile = f'{outputpath}_timeseries_{hp}.csv'
            data_all.to_csv(tsfile, sep=';')

            keyparampath = f'{outputpath}_key_parameters_{hp}.json'
            with open(keyparampath, 'w', encoding='utf-8') as file:
                json.dump(key_params, file, indent=4, sort_keys=True)

            cost_df.to_csv(f'{outputpath}_unit_cost_{hp}.csv', sep=';')
