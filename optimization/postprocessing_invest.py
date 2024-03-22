# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
from eco_funcs import (LCOH, bew_op_bonus, chp_bonus, emission_calc,
                       invest_stes, npv)
from helpers import calc_bew_el_cost_prim, calc_bew_el_cost_sub
from oemof.solph import views


def primary_network_invest(results, meta_results, data, param, use_hp):
    """
    Data postprocessing for the invest model of the primary district heating
    network.

    Parameters
    ----------

    results : dict of pandas.DataFrame
        results of the oemof.solph.processing.results method.
    
    meta_results : dict
        meta results of the oemof.solph.processing.meta_results method.

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.

    use_hp : bool
        Flag to set 'True' if a heat pump should be used in the energy system.
    """
    # Init
    key_params = dict()

    # Read out data of different nodes
    data_gnw = views.node(results, 'gas network')['sequences']
    data_enw = views.node(results, 'electricity network')['sequences']
    data_hnw = views.node(results, 'heat network')['sequences']
    data_ccet_node = views.node(results, 'ccet node')['sequences']
    data_ccet_no_bonus_node = views.node(results, 'ccet no bonus node')['sequences']
    data_spotmarket_node = views.node(results, 'spotmarket node')['sequences']
    data_st_tes = views.node(results, 'st-tes')['sequences']

    data_hnw_caps = views.node(results, 'heat network')['scalars']
    data_st_tes_cap = views.node(results, 'st-tes')['scalars'][
        (('st-tes', 'None'), 'invest')
        ]

    # Combine all data and relabel the column names
    data_all = pd.concat(
        [data_gnw, data_enw, data_hnw, data_ccet_node, data_ccet_no_bonus_node,
         data_spotmarket_node, data_st_tes],
        axis=1
        )
    result_labeling(data_all)
    data_all = data_all.loc[:,~data_all.columns.duplicated()].copy()

    data_caps = data_hnw_caps
    data_caps['cap_st-tes'] = data_st_tes_cap
    result_labeling(data_caps)

    # %% Deletion of unwated data
    drop_list = [
        'enw_to_spotmarket_node', 'P_ccet_no_bonus_node',
        'P_ccet_no_bonus_int_node', 'P_ccet_no_bonus_ext_node',
        'P_ccet_with_bonus_node'
        ]
    for col in data_all.columns:
        if ('status' in col[-1]) or ('state' in col) or (col in drop_list):
            data_all.drop(columns=col, inplace=True)

    data_caps = data_caps.to_frame().transpose()
    data_caps.reset_index(inplace=True, drop=True)
    for col in data_caps.columns:
        if ('total' in str(col)) or ('0' in str(col)):
            data_caps.drop(columns=col, inplace=True)

    hpcaporder = get_hp_cap_order(data_caps)

    for flow in ['P_in_', 'Q_out_']:
        data_all.rename(
            columns={
                flow+old: flow+new for old, new in hpcaporder.items()
                },
            inplace=True
            )

    data_caps.rename(
        columns={
            'cap_'+old: 'cap_'+new for old, new in hpcaporder.items()
            },
        inplace=True
        )

    try:
        data_all = data_all.reindex(sorted(data_all.columns), axis=1)
    except TypeError as e:
        print(f'TypeError in sorting data_all: {e}')

    try:
        data_caps = data_caps.reindex(sorted(data_caps.columns), axis=1)
    except TypeError as e:
        print(f'TypeError in sorting data_caps: {e}')


    # %% Investment and operational cost calculation
    cost_df = pd.DataFrame()

    # heat pump
    if use_hp:
        for i in range(1, param['hp']['amount']+1):
            hp_Q_N = data_caps.loc[0, f'cap_hp{i}']

            label = f'heat pump {i}'
            if hp_Q_N > 1e-3:
                hp_invest_N = (
                    param['hp']['inv_spez_m'] * hp_Q_N
                    + param['hp']['inv_spez_b']
                    )
            else:
                hp_invest_N = 0
            cost_df.loc['invest', label] = hp_invest_N
            cost_df.loc['op_cost_fix', label] = (
                param['hp']['op_cost_fix'] * hp_Q_N
                )
            cost_df.loc['op_cost_var', label] = (
                param['hp']['op_cost_var'] * data_all[f'Q_out_hp{i}'].sum()
                )
            cost_df.loc['op_cost', label] = (
                cost_df.loc['op_cost_fix', label]
                + cost_df.loc['op_cost_var', label]
            )

        # BEW invest bonus
        # Maximum possible invest bonus of 40% of total invest cost
        key_params['total_bew_invest_bonus'] = sum(
            cost_df.loc['invest', col] for col in cost_df.columns if 'heat pump' in col
            ) * param['param']['BEW']
        # Comply with upper limit of 100 Mio. €
        key_params['allowed_bew_invest_bonus'] = min(
            key_params['total_bew_invest_bonus'], 100e6
            )

        bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
            data, param
            )

        data_all['Q_out_hp'] = 0
        data_all['P_in_hp'] = 0
        for col in data_all.columns:
            if ('Q_out_hp' in col) and (col != 'Q_out_hp'):
                data_all['Q_out_hp'] += data_all[col]
            if ('P_in_hp' in col) and (col != 'P_in_hp'):
                data_all['P_in_hp'] += data_all[col]

    # ccet
    ccet_Q_N = data_caps.loc[0, 'cap_ccet']
    ccet_P_N = ccet_Q_N / data['ccet_eta_th'].mean() * data['ccet_eta_el'].mean()
    key_params['ccet_chp_bonus_real'] = chp_bonus(
        ccet_P_N*1e3, use_case='grid'
        ) * 10 
    cost_df = calc_cost('ccet', ccet_P_N, param, data_all['P_ccet'], cost_df)

    # for i in [1, 2]:
    #     ccet_Q_N = data_caps.loc[0, f'cap_ccet{i}']
    #     ccet_P_N = ccet_Q_N / data['ccet_eta_th'].mean() * data['ccet_eta_el'].mean()
    #     key_params['ccet_chp_bonus_real'] = chp_bonus(
    #         ccet_P_N*1e3, use_case='grid'
    #         ) * 10 
    #     cost_df = calc_cost('ccet', ccet_P_N, param, data_all[f'P_ccet{i}'], cost_df)

    # peak load boiler
    cost_df = calc_cost(
        'plb', data_caps.loc[0, 'cap_plb'], param, data_all['Q_plb'], cost_df,
        add_var_cost=param['param']['energy_tax']
        )

    # st-tes
    st_tes_Q_N = (
        data_caps.loc[0, 'cap_in_st-tes'] / param['st-tes']['Q_in_to_cap']
        )
    cost_df.loc['invest', 'st-tes'] = (
        param['st-tes']['inv_spez_m'] * st_tes_Q_N
        + param['st-tes']['inv_spez_b']
        )
    cost_df.loc['op_cost_fix', 'st-tes'] = (
        param['st-tes']['op_cost_fix'] * st_tes_Q_N
        )
    cost_df.loc['op_cost_var', 'st-tes'] = (
        param['st-tes']['op_cost_var'] * data_all['Q_in_st-tes'].sum()
        )
    cost_df.loc['op_cost', 'st-tes'] = (
        cost_df.loc['op_cost_fix', 'st-tes']
        + cost_df.loc['op_cost_var', 'st-tes']
        )

    # %% Primary energy and total cost calculation
    # total unit costs
    key_params['op_cost_total'] = cost_df.loc['op_cost'].sum()
    if use_hp:
        key_params['invest_total'] = (
            cost_df.loc['invest'].sum() - key_params['allowed_bew_invest_bonus']
            )
    else:
        key_params['invest_total'] = cost_df.loc['invest'].sum()

    # total gas costs
    key_params['cost_gas'] = (
        data_all['H_source'] * (
            data['gas_price']
            + data['co2_price'] * param['param']['ef_gas']
            )
        ).sum()

    # total electricity costs
    key_params['cost_el_grid'] = (
        data_all['P_source'] * (
            data['el_spot_price']
            + param['param']['elec_consumer_charges_grid']
            )
        ).sum()

    key_params['cost_el_internal'] = (
        data_all['P_ccet_no_bonus_int']
        * param['param']['elec_consumer_charges_self']
        ).sum()

    key_params['cost_el'] = (
        key_params['cost_el_grid'] + key_params['cost_el_internal']
        )

    key_params['cost_total'] = (
        key_params['op_cost_total'] + key_params['cost_gas']
        + key_params['cost_el']
        )

    # %% Revenue calculation
    key_params['revenues_spotmarket'] = (
        data_all['P_spotmarket'] * (
            data['el_spot_price'] + param['param']['vNNE']
            )
        ).sum()

    key_params['revenues_chpbonus'] = (
        data_all['P_ccet_with_bonus'].sum()
        * (param['param']['chp_bonus'] + param['param']['TEHG_bonus'])
        )

    if use_hp:
        if param['param']['use_BEW_op_bonus']:
            key_params['revenues_hp_bew_op_bonus'] = (
                (bew_op_bonus_Q_in_grid * data_all['P_source']
                    + bew_op_bonus_Q_in_self * data_all['P_ccet_no_bonus_int']
                ) * (data_all['Q_out_hp']/data_all['P_in_hp']).replace(
                    np.inf, 0
                    )
                ).sum()
        else:
            key_params['revenues_hp_bew_op_bonus'] = 0

    key_params['revenues_heat'] = (
        data_all['Q_demand'].sum() * param['param']['heat_price']
        )

    key_params['revenues_total'] = (
        key_params['revenues_spotmarket'] + key_params['revenues_chpbonus']
        + key_params['revenues_heat']
        )
    if use_hp:
        key_params['revenues_total'] += key_params['revenues_hp_bew_op_bonus']

    # %% Total balance
    key_params['balance_total'] = (
        key_params['revenues_total'] - key_params['cost_total']
        )

    # %% Meta results
    key_params['objective'] = meta_results['objective']
    key_params['gap'] = (
        (meta_results['problem']['Lower bound']
         - meta_results['objective'])
        / meta_results['problem']['Lower bound'] * 100
        )

    # %% Main economic results
    key_params['net present value'] = npv(
        key_params['invest_total'], key_params['balance_total'],
        i=param['param']['capital_interest'], n=param['param']['lifetime']
        )

    key_params['LCOH'] = LCOH(
        key_params['invest_total'], key_params['cost_total'],
        data_all['Q_demand'].sum(),
        revenue=(key_params['revenues_total']-key_params['revenues_heat']),
        i=param['param']['capital_interest'], n=param['param']['lifetime']
        )

    key_params['total_heat_demand'] = data_all['Q_demand'].sum()

    # %% Emission calculation
    data_all = emission_calc(data_all, data, param)
    key_params['Total Emissions OM'] = data_all['Emissions OM'].sum()
    key_params['Total Emissions DM'] = data_all['Emissions DM'].sum()

    return data_all, data_caps, key_params, cost_df


def sub_network_invest(results, meta_results, data, param, **kwargs):
    """
    Data postprocessing for the sub district heating network.

    Parameters
    ----------

    results : dict of pandas.DataFrame
        results of the oemof.solph.processing.results method.
    
    meta_results : dict
        meta results of the oemof.solph.processing.meta_results method.

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.
    """
    # Init
    key_params = dict()

    # Read out data of different nodes
    data_gnw = views.node(results, 'gas network')['sequences']
    data_enw = views.node(results, 'electricity network')['sequences']
    data_hnw = views.node(results, 'heat network')['sequences']
    data_sub_enw = views.node(results, 'sub electricity network')['sequences']
    data_sub_hnw = views.node(results, 'sub heat network')['sequences']
    data_ccet_node = views.node(results, 'ccet node')['sequences']
    data_ccet_no_bonus_node = views.node(results, 'ccet no bonus node')['sequences']
    data_spotmarket_node = views.node(results, 'spotmarket node')['sequences']
    data_st_tes = views.node(results, 'st-tes')['sequences']
    data_sub_st_tes = views.node(results, 'sub st-tes')['sequences']

    data_hnw_caps = views.node(results, 'heat network')['scalars']
    data_sub_hnw_caps = views.node(results, 'sub heat network')['scalars']
    data_sub_st_tes_cap = views.node(results, 'sub st-tes')['scalars'][
        (('sub st-tes', 'None'), 'invest')
        ]

    # Combine all data and relabel the column names
    data_all = pd.concat(
        [data_gnw, data_enw, data_hnw, data_sub_enw, data_sub_hnw,
         data_ccet_node, data_ccet_no_bonus_node, data_spotmarket_node,
         data_st_tes, data_sub_st_tes],
        axis=1
        )
    result_labeling(data_all)
    data_all = data_all.loc[:,~data_all.columns.duplicated()].copy()

    data_caps = pd.concat([data_hnw_caps, data_sub_hnw_caps], axis=0)
    data_caps['cap_sub_st-tes'] = data_sub_st_tes_cap
    result_labeling(data_caps)

    # %% Deletion of unwated data
    drop_list = [
        'enw_to_spotmarket_node', 'P_ccet_no_bonus_node',
        'P_ccet_no_bonus_int_node', 'P_ccet_no_bonus_ext_node',
        'P_ccet_with_bonus_node'
        ]
    for col in data_all.columns:
        if ('status' in col[-1]) or ('state' in col) or (col in drop_list):
            data_all.drop(columns=col, inplace=True)
    try:
        data_all = data_all.reindex(sorted(data_all.columns), axis=1)
    except TypeError as e:
        print(f'TypeError in sorting data_all: {e}')

    data_caps = data_caps.to_frame().transpose()
    data_caps.reset_index(inplace=True, drop=True)
    for col in data_caps.columns:
        if ('total' in str(col)) or ('0' in str(col)):
            data_caps.drop(columns=col, inplace=True)

    hpcaporder = get_hp_cap_order(data_caps)
    subhpcaporder = get_hp_cap_order(data_caps, hp_name='sub_hp')

    for flow in ['P_in_', 'Q_out_']:
        data_all.rename(
            columns={
                flow+old: flow+new for old, new in hpcaporder.items()
                },
            inplace=True
            )
        data_all.rename(
            columns={
                flow+old: flow+new for old, new in subhpcaporder.items()
                },
            inplace=True
            )

    data_caps.rename(
        columns={
            'cap_'+old: 'cap_'+new for old, new in hpcaporder.items()
            },
        inplace=True
        )
    data_caps.rename(
        columns={
            'cap_'+old: 'cap_'+new for old, new in subhpcaporder.items()
            },
        inplace=True
        )

    try:
        data_caps = data_caps.reindex(sorted(data_caps.columns), axis=1)
    except TypeError as e:
        print(f'TypeError in sorting data_caps: {e}')


    # %% Investment and operational cost calculation
    cost_df = pd.DataFrame()

    # heat pump
    for i in range(1, param['hp']['amount']+1):
        hp_Q_N = data_caps.loc[0, f'cap_hp{i}']

        label = f'heat pump {i}'
        if hp_Q_N > 1e-3:
            hp_invest_N = (
                param['hp']['inv_spez_m'] * hp_Q_N
                + param['hp']['inv_spez_b']
                )
        else:
            hp_invest_N = 0
        cost_df.loc['invest', label] = hp_invest_N
        cost_df.loc['op_cost_fix', label] = (
            param['hp']['op_cost_fix'] * hp_Q_N
            )
        cost_df.loc['op_cost_var', label] = (
            param['hp']['op_cost_var'] * data_all[f'Q_out_hp{i}'].sum()
            )
        cost_df.loc['op_cost', label] = (
            cost_df.loc['op_cost_fix', label]
            + cost_df.loc['op_cost_var', label]
        )

    data_all['Q_out_hp'] = 0
    data_all['P_in_hp'] = 0
    for col in data_all.columns:
        if ('Q_out_hp' in col) and (col != 'Q_out_hp'):
            data_all['Q_out_hp'] += data_all[col]
        if ('P_in_hp' in col) and (col != 'P_in_hp'):
            data_all['P_in_hp'] += data_all[col]

    bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
        data, param
        )

    # sub heat pump
    for i in range(1, param['sub hp']['amount']+1):
        sub_hp_Q_N = data_caps.loc[0, f'cap_sub_hp{i}']

        label = f'sub heat pump {i}'
        if sub_hp_Q_N > 1e-3:
            sub_hp_invest_N = (
                param['sub hp']['inv_spez_m'] * sub_hp_Q_N
                + param['sub hp']['inv_spez_b']
                )
        else:
            sub_hp_invest_N = 0
        cost_df.loc['invest', label] = sub_hp_invest_N
        cost_df.loc['op_cost_fix', label] = (
            param['sub hp']['op_cost_fix'] * sub_hp_Q_N
            )
        cost_df.loc['op_cost_var', label] = (
            param['sub hp']['op_cost_var'] * data_all[f'Q_out_sub_hp{i}'].sum()
            )
        cost_df.loc['op_cost', label] = (
            cost_df.loc['op_cost_fix', label]
            + cost_df.loc['op_cost_var', label]
        )

    data_all['Q_out_sub_hp'] = 0
    data_all['P_in_sub_hp'] = 0
    for col in data_all.columns:
        if ('Q_out_sub_hp' in col) and (col != 'Q_out_sub_hp'):
            data_all['Q_out_sub_hp'] += data_all[col]
        if ('P_in_sub_hp' in col) and (col != 'P_in_sub_hp'):
            data_all['P_in_sub_hp'] += data_all[col]

    bew_op_bonus_Q_in  = calc_bew_el_cost_sub(data, param)

    ccet_Q_N = param['ccet']['Q_N']
    ccet_P_N = ccet_Q_N / data['ccet_eta_th'].mean() * data['ccet_eta_el'].mean()
    key_params['ccet_chp_bonus_real'] = chp_bonus(
        ccet_P_N*1e3, use_case='grid'
        ) * 10 
    cost_df = calc_cost('ccet', ccet_P_N, param, data_all['P_ccet'], cost_df)

    # peak load boiler
    cost_df = calc_cost(
        'plb', param['plb']['Q_N'], param, data_all['Q_plb'], cost_df,
        add_var_cost=param['param']['energy_tax']
        )

    # st-tes
    st_tes_Q_N = param['st-tes']['Q']
    cost_df.loc['invest', 'st-tes'] = (
        param['st-tes']['inv_spez_m'] * st_tes_Q_N
        + param['st-tes']['inv_spez_b']
        )
    cost_df.loc['op_cost_fix', 'st-tes'] = (
        param['st-tes']['op_cost_fix'] * st_tes_Q_N
        )
    cost_df.loc['op_cost_var', 'st-tes'] = (
        param['st-tes']['op_cost_var'] * data_all['Q_in_st-tes'].sum()
        )
    cost_df.loc['op_cost', 'st-tes'] = (
        cost_df.loc['op_cost_fix', 'st-tes']
        + cost_df.loc['op_cost_var', 'st-tes']
        )

    # sub_st-tes
    sub_st_tes_Q_N = (
        data_caps.loc[0, 'cap_in_sub_st-tes']
        / param['sub st-tes']['Q_in_to_cap']
        )
    cost_df.loc['invest', 'sub st-tes'] = (
        param['sub st-tes']['inv_spez_m'] * sub_st_tes_Q_N
        + param['sub st-tes']['inv_spez_b']
        )
    cost_df.loc['op_cost_fix', 'sub st-tes'] = (
        param['sub st-tes']['op_cost_fix'] * sub_st_tes_Q_N
        )
    cost_df.loc['op_cost_var', 'sub st-tes'] = (
        param['sub st-tes']['op_cost_var'] * data_all['Q_in_sub_st-tes'].sum()
        )
    cost_df.loc['op_cost', 'sub st-tes'] = (
        cost_df.loc['op_cost_fix', 'sub st-tes']
        + cost_df.loc['op_cost_var', 'sub st-tes']
        )

    # BEW invest bonus
    # Maximum possible invest bonus of 40% of total invest cost
    bew_cols = []
    for col in cost_df.columns:
        if 'heat pump' in col:
            bew_cols.append(col)
    key_params['total_bew_invest_bonus'] = (
        cost_df.loc['invest', bew_cols].sum()
        ) * param['param']['BEW']
    # Comply with upper limit of 100 Mio. €
    key_params['allowed_bew_invest_bonus'] = min(
        key_params['total_bew_invest_bonus'], 100e6
        )

    # %% Primary energy and total cost calculation
    # total unit costs
    key_params['op_cost_total'] = cost_df.loc['op_cost'].sum()
    key_params['invest_total'] = (
        cost_df.loc['invest'].sum() - key_params['allowed_bew_invest_bonus']
        )

    # total gas costs
    key_params['cost_gas'] = (
        data_all['H_source'] * (
            data['gas_price']
            + data['co2_price'] * param['param']['ef_gas']
            )
        ).sum()

    # total electricity costs
    key_params['cost_el_grid'] = (
        data_all['P_source'] * (
            data['el_spot_price']
            + param['param']['elec_consumer_charges_grid']
            )
        ).sum()

    key_params['cost_el_internal'] = (
        data_all['P_ccet_no_bonus_int']
        * param['param']['elec_consumer_charges_self']
        ).sum()

    key_params['cost_el'] = (
        key_params['cost_el_grid'] + key_params['cost_el_internal']
        )

    key_params['cost_el_sub'] = (
        data_all['P_sub_source'] * (
            data['el_spot_price']
            + param['param']['elec_consumer_charges_grid']
            )
        ).sum()

    key_params['cost_total'] = (
        key_params['op_cost_total'] + key_params['cost_gas']
        + key_params['cost_el'] +key_params['cost_el_sub']
        )

    # %% Revenue calculation
    key_params['revenues_spotmarket'] = (
        data_all['P_spotmarket'] * (
            data['el_spot_price'] + param['param']['vNNE']
            )
        ).sum()

    key_params['revenues_chpbonus'] = (
        data_all['P_ccet_with_bonus'].sum()
        * (param['param']['chp_bonus'] + param['param']['TEHG_bonus'])
        )

    key_params['revenues_hp_bew_op_bonus'] = (
        (bew_op_bonus_Q_in_grid * data_all['P_source']
            + bew_op_bonus_Q_in_self * data_all['P_ccet_no_bonus_int']
        ) * (data_all['Q_out_hp']/data_all['P_in_hp']).replace(
            np.inf, 0
            )
        ).sum()

    key_params['revenues_sub_hp_bew_op_bonus'] = (
        bew_op_bonus_Q_in * data_all['P_sub_source']
        * (data_all['Q_out_sub_hp']/data_all['P_in_sub_hp']).replace(np.inf, 0)
        ).sum()

    key_params['revenues_heat'] = (
        data_all['Q_demand'].sum() * param['param']['heat_price']
        )

    key_params['revenues_sub_heat'] = (
        data_all['Q_sub_demand'].sum() * param['param']['heat_price']
        )

    key_params['revenues_total'] = (
        key_params['revenues_spotmarket'] + key_params['revenues_chpbonus']
        + key_params['revenues_hp_bew_op_bonus']
        + key_params['revenues_sub_hp_bew_op_bonus']
        + key_params['revenues_heat'] + key_params['revenues_sub_heat']
        )

    # %% Total balance
    key_params['balance_total'] = (
        key_params['revenues_total'] - key_params['cost_total']
        )

    # %% Meta results
    key_params['objective'] = meta_results['objective']
    key_params['gap'] = (
        (meta_results['problem']['Lower bound']
         - meta_results['objective'])
        / meta_results['problem']['Lower bound'] * 100
        )

    # %% Main economic results
    key_params['net present value'] = npv(
        key_params['invest_total'], key_params['balance_total'],
        i=param['param']['capital_interest'], n=param['param']['lifetime']
        )

    key_params['LCOH'] = LCOH(
        key_params['invest_total'], key_params['cost_total'],
        data_all['Q_demand'].sum()+data_all['Q_sub_demand'].sum(),
        revenue=(
            key_params['revenues_total']
            - key_params['revenues_heat']
            - key_params['revenues_sub_heat']
            ),
        i=param['param']['capital_interest'], n=param['param']['lifetime']
        )

    key_params['total_heat_demand'] = data_all['Q_demand'].sum()

    # %% Emission calculation
    data_all = emission_calc(data_all, data, param)
    key_params['Total Emissions OM'] = data_all['Emissions OM'].sum()
    key_params['Total Emissions DM'] = data_all['Emissions DM'].sum()
    key_params['Total Sub Emissions OM'] = data_all['Sub Emissions OM'].sum()
    key_params['Total Sub Emissions DM'] = data_all['Sub Emissions DM'].sum()

    return data_all, data_caps, key_params, cost_df


def IVgdh_network_invest(results, meta_results, data, param):
    
    """
    Data postprocessing for the 4th gen district heating network.

    Parameters
    ----------

    results : dict of pandas.DataFrame
        results of the oemof.solph.processing.results method.
    
    meta_results : dict
        meta results of the oemof.solph.processing.meta_results method.

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.
    """
    # Init
    key_params = {}

    # Read out data of different nodes
    data_bnw = views.node(results, 'biogas network')['sequences']
    data_enw = views.node(results, 'electricity network')['sequences']
    data_hnw = views.node(results, 'heat network')['sequences']
    data_ice_node = views.node(results, 'ice node')['sequences']
    data_ice_no_bonus_node = views.node(results, 'ice no bonus node')['sequences']
    data_spotmarket_node = views.node(results, 'spotmarket node')['sequences']
    data_s_tes = views.node(results, 's-tes')['sequences']

    data_hnw_caps = views.node(results, 'heat network')['scalars']
    data_s_tes_cap = views.node(results, 's-tes')['scalars'][
        (('s-tes', 'None'), 'invest')
        ]

    # Combine all data and relabel the column names
    data_all = pd.concat(
        [data_bnw, data_enw, data_hnw, data_ice_node, data_ice_no_bonus_node,
         data_spotmarket_node, data_s_tes],
        axis=1
        )
    result_labeling(data_all)
    data_all = data_all.loc[:,~data_all.columns.duplicated()].copy()

    if len(data_all.index) == 8761:
        data_all = data_all.iloc[:-1, :]

    data_caps = data_hnw_caps
    data_caps['cap_s-tes'] = data_s_tes_cap
    result_labeling(data_caps)

    # Remove unnecessairy columns
    for col in data_all.columns:
        if ('status' in str(col)) or ('state' in str(col)):
            data_all.drop(columns=col, inplace=True)

    data_caps = data_caps.to_frame().transpose()
    data_caps.reset_index(inplace=True, drop=True)
    for col in data_caps.columns:
        if ('total' in str(col)) or ('0' in str(col)):
            data_caps.drop(columns=col, inplace=True)

    hpcaporder = get_hp_cap_order(data_caps)

    for flow in ['P_in_', 'Q_out_']:
        data_all.rename(
            columns={
                flow+old: flow+new for old, new in hpcaporder.items()
                },
            inplace=True
            )

    data_caps.rename(
        columns={
            'cap_'+old: 'cap_'+new for old, new in hpcaporder.items()
            },
        inplace=True
        )

    try:
        data_all = data_all.reindex(sorted(data_all.columns), axis=1)
    except TypeError as e:
        print(f'TypeError in sorting data_all: {e}')

    try:
        data_caps = data_caps.reindex(sorted(data_caps.columns), axis=1)
    except TypeError as e:
        print(f'TypeError in sorting data_caps: {e}')

    data_caps.reset_index(inplace=True, drop=True)

    # %% Investment and operational cost calculation
    cost_df = pd.DataFrame()

    # heat pump
    for i in range(1, param['hp']['amount']+1):
        hp_Q_N = data_caps.loc[0, f'cap_hp{i}']

        label = f'heat pump {i}'
        if hp_Q_N > 1e-3:
            hp_invest_N = (
                param['hp']['inv_spez_m'] * hp_Q_N
                + param['hp']['inv_spez_b']
                )
        else:
            hp_invest_N = 0
        cost_df.loc['invest', label] = hp_invest_N
        cost_df.loc['op_cost_fix', label] = (
            param['hp']['op_cost_fix'] * hp_Q_N
            )
        cost_df.loc['op_cost_var', label] = (
            param['hp']['op_cost_var'] * data_all[f'Q_out_hp{i}'].sum()
            )
        cost_df.loc['op_cost', label] = (
            cost_df.loc['op_cost_fix', label]
            + cost_df.loc['op_cost_var', label]
        )

    bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
        data, param
        )

    data_all['Q_out_hp'] = 0
    data_all['P_in_hp'] = 0
    for col in data_all.columns:
        if ('Q_out_hp' in col) and (col != 'Q_out_hp'):
            data_all['Q_out_hp'] += data_all[col]
        if ('P_in_hp' in col) and (col != 'P_in_hp'):
            data_all['P_in_hp'] += data_all[col]

    # ice
    ice_Q_N = data_caps.loc[0, 'cap_ice']
    ice_P_N = ice_Q_N / data['ice_eta_th'].mean() * data['ice_eta_el'].mean()
    key_params['ice_chp_bonus_real'] = chp_bonus(
        ice_P_N*1e3, use_case='grid'
        ) * 10 
    cost_df = calc_cost('ice', ice_P_N, param, data_all['P_ice'], cost_df)

    # Solar thermal collectors
    if 'cap_sol' in data_caps.columns:
        sol_A_N = data_caps.loc[0, 'cap_sol']
    else:
        sol_A_N = param['sol']['A_N_CHECK_IF_SET']

    cost_df.loc['invest', 'solar'] =  (
        param['sol']['inv_spez_m'] * sol_A_N
        + param['sol']['inv_spez_b']
        )
    cost_df.loc['op_cost_fix', 'solar'] = (
        param['sol']['op_cost_fix'] * data_all['Q_sol'].sum()  # energinet
        )
    cost_df.loc['op_cost_var', 'solar'] = (
        param['sol']['op_cost_var'] * data_all['Q_sol'].sum()  # energinet
        )
    cost_df.loc['op_cost', 'solar'] = (
        cost_df.loc['op_cost_fix', 'solar']
        + cost_df.loc['op_cost_var', 'solar']
    )

    # s-tes
    s_tes_Q_N = data_caps.loc[0, 'cap_s-tes']
    cost_df.loc['invest', 's-tes'] = (
        param['s-tes']['inv_spez_m'] * s_tes_Q_N
        + param['s-tes']['inv_spez_b']
        )
    cost_df.loc['op_cost_fix', 's-tes'] = (
        param['s-tes']['op_cost_fix'] * s_tes_Q_N
        )
    cost_df.loc['op_cost_var', 's-tes'] = (
        param['s-tes']['op_cost_var'] * data_all['Q_in_s-tes'].sum()
        )
    cost_df.loc['op_cost', 's-tes'] = (
        cost_df.loc['op_cost_fix', 's-tes']
        + cost_df.loc['op_cost_var', 's-tes']
        )

    # BEW invest bonus
    # Maximum possible invest bonus of 40% of total invest cost
    bew_inv_units = ['heat pump', 'ice', 'solar']
    bew_cols = []
    for col in cost_df.columns:
        for bew_unit in bew_inv_units:
            if bew_unit in col:
                bew_cols.append(col)
    key_params['total_bew_invest_bonus'] = (
        cost_df.loc['invest', bew_cols].sum()
        ) * param['param']['BEW']
    # Comply with upper limit of 100 Mio. €
    key_params['allowed_bew_invest_bonus'] = min(
        key_params['total_bew_invest_bonus'], 100e6
        )

    # %% Primary energy and total cost calculation
    # total unit costs
    key_params['op_cost_total'] = cost_df.loc['op_cost'].sum()
    key_params['invest_total'] = (
        cost_df.loc['invest'].sum() - key_params['allowed_bew_invest_bonus']
        )

    # total biogas costs
    key_params['cost_biogas'] = (
        data_all['H_bio_source'] * (
            data['biogas_price']
            + data['co2_price'] * param['param']['ef_biogas']
            )
        ).sum()

    # total electricity costs
    key_params['cost_el_grid'] = (
        data_all['P_source'] * (
            data['el_spot_price']
            + param['param']['elec_consumer_charges_grid']
            )
        ).sum()

    key_params['cost_el_internal'] = (
        data_all['P_ice_no_bonus_int']
        * param['param']['elec_consumer_charges_self']
        ).sum()

    key_params['cost_el'] = (
        key_params['cost_el_grid'] + key_params['cost_el_internal']
        )

    key_params['cost_total'] = (
        key_params['op_cost_total'] + key_params['cost_biogas']
        + key_params['cost_el']
        )

    # %% Revenue calculation
    key_params['revenues_spotmarket'] = (
        data_all['P_spotmarket'] * (
            data['el_spot_price'] + param['param']['vNNE']
            )
        ).sum()

    key_params['revenues_chpbonus'] = (
        data_all['P_ice_with_bonus'].sum()
        * (param['param']['chp_bonus'] + param['param']['TEHG_bonus'])
        )

    key_params['revenues_hp_bew_op_bonus'] = (
        (bew_op_bonus_Q_in_grid * data_all['P_source']
            + bew_op_bonus_Q_in_self * data_all['P_ice_no_bonus_int']
        ) * (data_all['Q_out_hp']/data_all['P_in_hp']).replace(
            np.inf, 0
            )
        ).sum()

    key_params['revenues_heat'] = (
        data_all['Q_demand'].sum() * param['param']['heat_price']
        )

    key_params['revenues_total'] = (
        key_params['revenues_spotmarket'] + key_params['revenues_chpbonus']
        + key_params['revenues_hp_bew_op_bonus'] + key_params['revenues_heat']
        )

    # %% Total balance
    key_params['balance_total'] = (
        key_params['revenues_total'] - key_params['cost_total']
        )

    # %% Meta results
    key_params['objective'] = meta_results['objective']
    key_params['gap'] = (
        (meta_results['problem']['Lower bound']
         - meta_results['objective'])
        / meta_results['problem']['Lower bound'] * 100
        )

    # %% Main economic results
    key_params['net present value'] = npv(
        key_params['invest_total'], key_params['balance_total'],
        i=param['param']['capital_interest'], n=param['param']['lifetime']
        )

    key_params['LCOH'] = LCOH(
        key_params['invest_total'], key_params['cost_total'],
        data_all['Q_demand'].sum(),
        revenue=(key_params['revenues_total']-key_params['revenues_heat']),
        i=param['param']['capital_interest'], n=param['param']['lifetime']
        )

    key_params['total_heat_demand'] = data_all['Q_demand'].sum()

    # %% Emission calculation
    data_all = emission_calc(data_all, data, param)
    key_params['Total Emissions OM'] = data_all['Emissions OM'].sum()
    key_params['Total Emissions DM'] = data_all['Emissions DM'].sum()

    return data_all, data_caps, key_params, cost_df


def result_labeling(df, labeldictpath='labeldict.csv'):
    """
    Relabel the column names of oemof.solve result dataframes.

    Parameters
    ----------

    df : pandas.DataFrame
        DataFrame containing the results whose column names should be relabeled.
    
    labeldictpath : str
        Relative path to the labeldict csv file. Defaults to a path in the same
        directory.
    """
    labeldict_csv = pd.read_csv(labeldictpath, sep=';', na_filter=False)

    labeldict = dict()
    for idx in labeldict_csv.index:
        labeldict[
            ((labeldict_csv.loc[idx, 'name_out'],
              labeldict_csv.loc[idx, 'name_in']),
              labeldict_csv.loc[idx, 'type'])
            ] = labeldict_csv.loc[idx, 'label']

    if isinstance(df, pd.DataFrame):
        for col in df.columns:
            if col in labeldict.keys():
                df.rename(columns={col: labeldict[col]}, inplace=True)
            else:
                print(f'Column name "{col}" not in "{labeldictpath}".')
    elif isinstance(df, pd.Series):
        for idx in df.index:
            if idx in labeldict.keys():
                df.rename(index={idx: labeldict[idx]}, inplace=True)
            else:
                print(f'Column name "{idx}" not in "{labeldictpath}".')


def calc_cost(label, E_N, param, uc, cost_df, add_var_cost=None):
    """
    Calculate invest and operational cost for a unit.

    Parameters
    ----------

    label : str
        Label of unit to be used as column name in cost DataFrame.

    E_N : float
        Nominal rated energy that the specific cost relate to.

    param : dict
        JSON parameter file of user defined constants.

    uc : pandas.DataFrame
        DataFrame containing the units results of the unit commitment
        optimization.

    cost_df : pandas.DataFrame
        DataFrame in which the calculated cost should be inserted.
    """
    cost_df.loc['invest', label] =  param[label]['inv_spez'] * E_N
    cost_df.loc['op_cost_fix', label] = param[label]['op_cost_fix'] * E_N
    cost_df.loc['op_cost_var', label] = (
        param[label]['op_cost_var'] * uc.sum()
        )
    if add_var_cost:
        cost_df.loc['op_cost_var', label] += add_var_cost * uc.sum()
    cost_df.loc['op_cost', label] = (
        cost_df.loc['op_cost_fix', label] + cost_df.loc['op_cost_var', label]
        )

    return cost_df


def get_hp_cap_order(data_caps, hp_name='hp', descending=True):
    """
    Sort heat pumps by capacity to allow renaming.

    Parameters
    ----------
    data_caps : pandas.DataFrame
        Resulting capacities of all investment optimized units. (Index is
        currently assumed to be the integer value 0.)

    hp_name : str
        Name of heat pump in results. For now either 'hp' or 'sub_hp'.

    descending : bool
        Boolean flag whether to sort in a descending or ascending order. Default
        is True -> descending order.

    Returns
    -------
    renamedict: dict
        Dictionairy with string pairs of key and value, corresponding to
        previous and new name/order (e.g. 'hp1' is key and should be renamed to
        its value 'hp6', since it has the sixth lowest capacity)
    """
    ascending = not descending
    hpcols = [f'cap_{hp_name}{i}' for i in range(1, 8)]

    colssorted = data_caps[hpcols].sort_values(
        by=0, axis=1, ascending=ascending
        ).columns.to_list()

    renamedict = {
        col[4:]: f'{hp_name}{i}' for i, col in enumerate(colssorted, start=1)
        }

    return renamedict


def check_chp_bonus(data_all, data_caps, data, param):
    """
    Check the resulting chp bonus based on assumptions againts real values.
    
    Parameters
    ----------
    data_all : pandas.DataFrame
        Resulting unit commitment time series.

    data_caps : pandas.DataFrame
        Resulting capacities of all investment optimized units.

    data : pandas.DataFrame
        Input time series parameters.

    param : dict
        Constant input parameters.
    """
    W_total_chp_bonus = data_all['P_ccet_with_bonus'].sum()
    P_nom = (
        data_caps.loc[0, 'cap_ccet']/data['ccet_eta_th'].mean()
        * data['ccet_eta_el'].mean()
        )
    W_max_correct_chp_bonus = P_nom * param['param']['h_max_chp_bonus']

    revenue_simulation = W_total_chp_bonus * param['param']['chp_bonus']
    revenue_real = (
        W_max_correct_chp_bonus * chp_bonus(P_nom*1e3, use_case='grid') * 10
        )

    return (
        W_total_chp_bonus, W_max_correct_chp_bonus,
        revenue_simulation, revenue_real
        )


def check_bew_bonus(data_all, data_caps, data, param):
    """
    Check the resulting BEW investment and operating bonus based on assumptions
    againts real values.
    
    Parameters
    ----------
    data_all : pandas.DataFrame
        Resulting unit commitment time series.

    data_caps : pandas.DataFrame
        Resulting capacities of all investment optimized units.

    data : pandas.DataFrame
        Input time series parameters.

    param : dict
        Constant input parameters.
    """
    # %% Invest cost subsidies
    hp_inv_total = 0
    for i in range(1, param['hp']['amount']+1):
        hp_inv_total += (
            param['hp']['inv_spez_m'] * data_caps.loc[0, f'cap_hp{i}']
            + param['hp']['inv_spez_b']
            )
    hp_inv_bonus = hp_inv_total * param['param']['BEW']

    if 'sub hp' in param.keys():
        sub_hp_inv_total = 0
        for i in range(1, param['sub hp']['amount']+1):
            sub_hp_inv_total += (
                param['sub hp']['inv_spez_m'] * data_caps.loc[0, f'cap_sub_hp{i}']
                + param['sub hp']['inv_spez_b']
                )
        sub_hp_inv_bonus = sub_hp_inv_total * param['param']['BEW']

    key_params = {}

    bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
        data, param
        )

    data_all['Q_out_hp'] = 0
    data_all['P_in_hp'] = 0
    for col in data_all.columns:
        if ('Q_out_hp' in col) and (col != 'Q_out_hp'):
            data_all['Q_out_hp'] += data_all[col]
        if ('P_in_hp' in col) and (col != 'P_in_hp'):
            data_all['P_in_hp'] += data_all[col]

    key_params['hp_bew_op_bonus_total'] = (
        (bew_op_bonus_Q_in_grid * data_all['P_source']
            + bew_op_bonus_Q_in_self * data_all['P_ccet_no_bonus_int']
        ) * (data_all['Q_out_hp']/data_all['P_in_hp']).replace(
            np.inf, 0
            )
        ).sum()

    key_params['hp_el_cost_total'] = (
        data_all['P_source'] * (
            data['el_spot_price']
            + param['param']['elec_consumer_charges_grid']
            )
        + data_all['P_ccet_no_bonus_int']
        * param['param']['elec_consumer_charges_self']
        ).sum()

    bew_op_bonus_Q_in = calc_bew_el_cost_sub(data, param)

    data_all['Q_out_sub_hp'] = 0
    data_all['P_in_sub_hp'] = 0
    for col in data_all.columns:
        if 'Q_out_sub_hp' in col:
            data_all['Q_out_sub_hp'] += data_all[col]
        if 'P_in_sub_hp' in col:
            data_all['P_in_sub_hp'] += data_all[col]

    key_params[f'sub_hp_bew_op_bonus_total'] = (
        bew_op_bonus_Q_in * data_all['Q_out_sub_hp']
        ).sum()

    key_params['sub_hp_el_cost_total'] = (
        data_all['P_in_sub_hp'] * (
            data['el_spot_price']
            + param['param']['elec_consumer_charges_grid']
            )
        ).sum()

    if not 'sub hp' in param.keys():
        return hp_inv_bonus, key_params
    else:
        return hp_inv_bonus, sub_hp_inv_bonus, key_params


def check_subsidies(data_all, data_caps, data, param, savepath, use_hp=True):
    """
    Check all subsidies (chp and bew bonusses) based on assumptions againts real
    values.
    
    Parameters
    ----------
    data_all : pandas.DataFrame
        Resulting unit commitment time series.

    data_caps : pandas.DataFrame
        Resulting capacities of all investment optimized units.

    data : pandas.DataFrame
        Input time series parameters.

    param : dict
        Constant input parameters.
    """
    W_tot_chp_bonus, W_max_real_chp_bonus, rev_sim, rev_real = check_chp_bonus(
        data_all, data_caps, data, param
        )

    df = pd.DataFrame()
    df.loc['value', 'chp_W_surplus'] = W_tot_chp_bonus - W_max_real_chp_bonus
    df.loc['value', 'chp_rev_surplus'] = rev_sim - rev_real

    if use_hp:
        hp_inv_bonus, df_bew_op_bonus, total_el_cost = check_bew_bonus(
            data_all, data_caps, data, param
            )

        df.loc['value', 'bew_inv_surplus'] = hp_inv_bonus - 100e6
        df.loc['value', 'bew_op_surplus'] = (
            df_bew_op_bonus.loc['total_bew_op_bonus_simulation', :].sum()
            - df_bew_op_bonus.loc['total_bew_op_bonus_real', :].sum()
            )
        df.loc['value', 'bew_op_limit_surplus'] = (
            df_bew_op_bonus.loc['total_bew_op_bonus_simulation', :].sum()
            - total_el_cost * 0.9
            )

    df.to_csv(savepath, sep=';')
