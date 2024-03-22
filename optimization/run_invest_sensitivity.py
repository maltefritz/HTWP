import json
import os

import energy_system_invest
import pandas as pd
import postprocessing_invest

# %% Simulation parameters

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

# Relative gas prices
gas_prices = [1+i/100 for i in range(1, 81, 1)]
print(gas_prices)

for es in energy_systems:
    for scn in scenarios:
        for hp in hps:
            print(f'\n##### {es}{scn}: {hp} #####\n')

            # %% Read data
            inputpath = os.path.join(
                __file__, '..', longnames[es], 'input', es+scn
                )

            datafile = f'{inputpath}_invest_data_{hp}.csv'
            data = pd.read_csv(
                datafile, sep=';', index_col=0, parse_dates=True
                )

            base_gp = data['gas_price'].mean()

            paramfile = f'{inputpath}_invest_param_{hp}.json'
            with open(paramfile, 'r', encoding='utf-8') as file:
                param = json.load(file)

            # %% Prepare output file structure
            rootoutputpath = os.path.join(
                __file__, '..', longnames[es], 'output', f'{es}{scn}_sensitivity'
                )
            if not os.path.exists(rootoutputpath):
                os.mkdir(rootoutputpath)
            outputpath = os.path.join(rootoutputpath, f'{es}{scn}_invest')


            # %% Execute optimization
            logpath = os.path.join(
                longnames[es], 'output', f'{es}{scn}_sensitivity',
                f'{es}{scn}_invest_GUROBILOG_{hp}.log'
                )
            solutionpath = os.path.join(
                longnames[es], 'output', f'{es}{scn}_sensitivity',
                f'{es}{scn}_invest_SOLUTION_{hp}.sol'
                )
            param['param']['mipgap'] = 1e-3
            param['param']['TimeLimit'] = 60*60*2
            param['param']['MIPFocus'] = 2

            print(json.dumps(param, indent=4))

            # %% Read in or prepare meta result DataFrames
            captablepath = f'{outputpath}_ALLcapacities_{hp}.csv'
            if os.path.exists(captablepath):
                captable = pd.read_csv(captablepath, sep=';', index_col=0)
            else:
                captable = pd.DataFrame()

            heattablepath = f'{outputpath}_ALLcoverages_{hp}.csv'
            if os.path.exists(heattablepath):
                heattable = pd.read_csv(heattablepath, sep=';', index_col=0)
            else:
                heattable = pd.DataFrame()

            # %% Sensitivity analysis loop
            for gp in gas_prices:
                data['gas_price'] = gp * base_gp
                print('Mean gas price: ' + str(data['gas_price'].mean()) + ' €')
                print(f'Relative to base gas price: {gp:.2f}\n')
                if os.path.exists(f'{outputpath}_capacities_{hp}_{gp:.2f}xGAS_PRICE.csv'):
                    continue

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

                # %% Meta Results
                for cap in data_caps.columns:
                    captable.loc[gp, cap] = data_caps.loc[0, cap]
                captable.loc[gp, 'MIPGap'] = round(key_params['gap'], 3)
                captable.sort_index(inplace=True)
                captable.to_csv(captablepath, sep=';')

                for col in data_all.columns:
                    if 'Q' in col:
                        heattable.loc[gp, col] = data_all[col].sum()
                heattable.loc[gp, 'MIPGap'] = round(key_params['gap'], 3)
                heattable.sort_index(inplace=True)
                heattable.to_csv(heattablepath, sep=';')

                # %% Setup specific results
                capsfile = f'{outputpath}_capacities_{hp}_{gp:.2f}xGAS_PRICE.csv'
                data_caps.to_csv(capsfile, sep=';')

                tsfile = f'{outputpath}_timeseries_{hp}_{gp:.2f}xGAS_PRICE.csv'
                data_all.to_csv(tsfile, sep=';')

                keyparampath = (
                    f'{outputpath}_key_parameters_{hp}_{gp:.2f}xGAS_PRICE.json'
                    )
                with open(keyparampath, 'w', encoding='utf-8') as file:
                    json.dump(key_params, file, indent=4, sort_keys=True)

                cost_df.to_csv(
                    f'{outputpath}_unit_cost_{hp}_{gp:.2f}xGAS_PRICE.csv', sep=';'
                    )
