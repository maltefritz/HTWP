# -*- coding: utf-8 -*-

import oemof.solph as solph
import pandas as pd
from eco_funcs import bew_op_bonus, calc_bwsf, chp_bonus
from energy_system import primary_network
from helpers import calc_bew_el_cost_prim, calc_bew_el_cost_sub


def primary_network_invest(data, param, use_hp=True, return_unsolved=False):
    """
    Generate and solve mixed integer linear problem of the primary network.

    Parameters
    ----------

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.

    use_hp : bool
        Flag to set 'True' if a heat pump should be used in the energy system.
        (Default: 'True')

    return_unsolved : bool
        Flag to set 'True' if the energy system should be returned unsolved.
        (Default: 'False')
    """
    # %% Calculate global parameters
    bwsf = calc_bwsf(
        param['param']['capital_interest'], param['param']['lifetime']
        )

    # %% Create time index
    periods = len(data)
    date_time_index = pd.date_range(data.index[0], periods=periods, freq='h')

    # %% Create energy system
    energy_system = solph.EnergySystem(
        timeindex=date_time_index, infer_last_interval=False
        )

    # %% Busses
    gnw = solph.Bus(label='gas network')
    enw = solph.Bus(label='electricity network')
    hnw = solph.Bus(label='heat network')

    ccet_node = solph.Bus(label='ccet node')
    ccet_no_bonus_node = solph.Bus(label='ccet no bonus node')
    spotmarket_node = solph.Bus(label='spotmarket node')

    energy_system.add(
        gnw, enw, hnw, ccet_node, ccet_no_bonus_node, spotmarket_node
        )

    # %% Sources
    gas_source = solph.components.Source(
        label='gas source',
        outputs={
            gnw: solph.flows.Flow(
                variable_costs=(
                    data['gas_price']
                    + (data['co2_price'] * param['param']['ef_gas'])
                    ))}
        )

    # BEW operational bonus
    try:
        if param['param']['use_BEW_op_bonus']:
            bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
                data, param
                )
            hp_P_max = (data['hp_Q_max'] - data['hp_c_0']) / data['hp_c_1']

            elec_source_cost = (
                param['param']['elec_consumer_charges_grid']
                - param['param']['elec_consumer_charges_self']
                + data['el_spot_price']
                + (data['hp_Q_max'] / hp_P_max) * (
                    - bew_op_bonus_Q_in_grid
                    + bew_op_bonus_Q_in_self
                    )
                )
        else:
            bew_op_bonus_Q_in_self = 0
            elec_source_cost = (
                param['param']['elec_consumer_charges_grid']
                - param['param']['elec_consumer_charges_self']
                + data['el_spot_price']
                )
    except KeyError as e:
        print(f'KeyError Exception: {e}')
        elec_source_cost = (
            param['param']['elec_consumer_charges_grid']
            - param['param']['elec_consumer_charges_self']
            + data['el_spot_price']
            )

    elec_source = solph.components.Source(
        label='electricity source',
        outputs={
            enw: solph.flows.Flow(
                variable_costs=elec_source_cost
                )
            }
        )

    energy_system.add(gas_source, elec_source)

    # %% Sinks
    elec_sink = solph.components.Sink(
        label='spotmarket',
        inputs={
            spotmarket_node: solph.flows.Flow(
                variable_costs=(
                    -data['el_spot_price'] - param['param']['vNNE']
                    ))}
        )

    heat_sink = solph.components.Sink(
        label='heat demand',
        inputs={
            hnw: solph.flows.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['heat_demand'].max(),
                fix=data['heat_demand']/data['heat_demand'].max()
                )}
        )

    energy_system.add(elec_sink, heat_sink)

    # %% Heat pump
    if use_hp:
        for i in range(1, param['hp']['amount']+1):
            hp = solph.components.OffsetConverter(
                label=f'heat pump {i}',
                inputs={
                    enw: solph.flows.Flow(
                        variable_costs=param['param']['elec_consumer_charges_self'],
                    )
                },
                outputs={
                    hnw: solph.flows.Flow(
                        variable_costs=(
                            param['hp']['op_cost_var'] - bew_op_bonus_Q_in_self
                            ),
                        investment=solph.Investment(
                            ep_costs=(
                                param['hp']['inv_spez_m'] / bwsf
                                * (1 - param['param']['BEW'])
                                ),
                            maximum=param['hp']['cap_max'],
                            minimum=param['hp']['cap_min'],
                            offset=(
                                param['hp']['inv_spez_b'] / bwsf
                                * (1 - param['param']['BEW'])
                                ),
                            nonconvex=solph.NonConvex()
                            ),
                        max=data['hp_Q_max'],
                        min=data['hp_Q_min'],
                        nonconvex=solph.NonConvex()
                        )
                    },
                coefficients=[data['hp_c_0'], data['hp_c_1']]
                )

            energy_system.add(hp)

    # %% Combined cycle extraction turbine
    ccet = solph.components.Converter(
        label='ccet',
        inputs={
            gnw: solph.flows.Flow()
            },
        outputs={
            ccet_node: solph.flows.Flow(
                variable_costs=param['ccet']['op_cost_var']
                ),
            hnw: solph.flows.Flow(
                investment=solph.Investment(
                    ep_costs=(param['ccet']['inv_spez'] / bwsf),
                    maximum=param['ccet']['cap_max'],
                    minimum=param['ccet']['cap_min'],
                    nonconvex=solph.NonConvex()
                    ),
                max=(data['ccet_H_max']*data['ccet_eta_th']),
                min=(data['ccet_H_min']*data['ccet_eta_th']),
                nonconvex=solph.NonConvex()
                )
            },
        conversion_factors={
            ccet_node: data['ccet_eta_el'],
            hnw: data['ccet_eta_th']
            }
        )

    energy_system.add(ccet)

    # for i in [1, 2]:
    #     ccet = solph.components.Converter(
    #         label=f'ccet {i}',
    #         inputs={
    #             gnw: solph.flows.Flow()
    #             },
    #         outputs={
    #             ccet_node: solph.flows.Flow(
    #                 variable_costs=param['ccet']['op_cost_var']
    #                 ),
    #             hnw: solph.flows.Flow(
    #                 investment=solph.Investment(
    #                     ep_costs=(param['ccet']['inv_spez'] / bwsf),
    #                     maximum=param['ccet']['cap_max'],
    #                     minimum=param['ccet']['cap_min'],
    #                     nonconvex=solph.NonConvex()
    #                     ),
    #                 max=(data['ccet_H_max']*data['ccet_eta_th']),
    #                 min=(data['ccet_H_min']*data['ccet_eta_th']),
    #                 nonconvex=solph.NonConvex()
    #                 )
    #             },
    #         conversion_factors={
    #             ccet_node: data['ccet_eta_el'],
    #             hnw: data['ccet_eta_th']
    #             }
    #         )

    #     energy_system.add(ccet)

    # %% Peak load boiler
    plb = solph.components.Converter(
        label='peak load boiler',
        inputs={gnw: solph.flows.Flow()},
        outputs={
            hnw: solph.flows.Flow(
                investment=solph.Investment(
                    ep_costs=(param['plb']['inv_spez'] / bwsf),
                    maximum=param['plb']['cap_max'],
                    minimum=param['plb']['cap_min'],
                    nonconvex=solph.NonConvex()
                    ),
                max=1,
                min=0,
                variable_costs=(
                    param['plb']['op_cost_var'] + param['param']['energy_tax'])
                )},
        conversion_factors={hnw: param['plb']['eta']}
        )

    energy_system.add(plb)

    # %% Short term storage
    st_tes = solph.components.GenericStorage(
        label='st-tes',
        investment=solph.Investment(
            ep_costs=(param['st-tes']['inv_spez_m'] / bwsf),
            maximum=param['st-tes']['cap_max'],
            minimum=param['st-tes']['cap_min'],
            offset=(param['st-tes']['inv_spez_b'] / bwsf),
            nonconvex=True
            ),
        inputs={
            hnw: solph.flows.Flow(
                variable_costs=param['st-tes']['op_cost_var'],
                )
            },
        outputs={
            hnw: solph.flows.Flow(
                variable_costs=param['st-tes']['op_cost_var'],
                )
            },
        invest_relation_input_capacity=param['st-tes']['Q_in_to_cap'],
        invest_relation_output_capacity=param['st-tes']['Q_out_to_cap'],
        initial_storage_level=param['st-tes']['init_storage'],
        loss_rate=param['st-tes']['Q_rel_loss'],
        inflow_conversion_factor=param['st-tes']['inflow_conv'],
        outflow_conversion_factor=param['st-tes']['outflow_conv'])

    energy_system.add(st_tes)

    # %% Auxillary components
    ccet_P_N = (
        (data['heat_demand'].max() * 1/3)
        / data['ccet_eta_th'].mean()
        * data['ccet_eta_el'].mean()
        )
    ccet_chp_bonus = param['param']['chp_bonus']

    ccet_with_chp_bonus = solph.components.Converter(
        label='ccet with chp bonus',
        inputs={ccet_node: solph.flows.Flow()},
        outputs={
            spotmarket_node: solph.flows.Flow(
                nominal_value=ccet_P_N,
                max=1.0,
                min=0.0,
                full_load_time_max=param['param']['h_max_chp_bonus'],
                variable_costs=(
                    -ccet_chp_bonus - param['param']['TEHG_bonus'])
                )},
        conversion_factors={enw: 1}
        )

    ccet_no_chp_bonus = solph.components.Converter(
        label='ccet no chp bonus',
        inputs={ccet_node: solph.Flow()},
        outputs={ccet_no_bonus_node: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={ccet_no_bonus_node: 1}
        )

    ccet_no_chp_bonus_int = solph.components.Converter(
        label='ccet no chp bonus internally',
        inputs={ccet_no_bonus_node: solph.Flow()},
        outputs={enw: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={enw: 1}
        )

    ccet_no_chp_bonus_ext = solph.components.Converter(
        label='ccet no chp bonus externally',
        inputs={ccet_no_bonus_node: solph.Flow()},
        outputs={spotmarket_node: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={spotmarket_node: 1}
        )

    energy_system.add(
        ccet_with_chp_bonus, ccet_no_chp_bonus,
        ccet_no_chp_bonus_int, ccet_no_chp_bonus_ext
        )

    # %% Return unsolved
    if return_unsolved:
        return energy_system

    # %% Solve
    model = solph.Model(energy_system)
    # model.write('my_model.lp', io_options={'symbolic_solver_labels': True})
    solveroptions = {}
    if 'mipgap' in param['param'].keys():
        solveroptions['MIPGap'] = param['param']['mipgap']
    if 'TimeLimit' in param['param'].keys():
        solveroptions['TimeLimit'] = param['param']['TimeLimit']
    if 'MIPFocus' in param['param'].keys():
        solveroptions['MIPFocus'] = param['param']['MIPFocus']
    if 'SolverLogPath' in param['param'].keys():
        solveroptions['LogFile'] = param['param']['SolverLogPath']
    if 'ResultFile' in param['param'].keys():
        solveroptions['ResultFile'] = param['param']['ResultFile']
    if 'InputFile' in param['param'].keys():
        solveroptions['InputFile'] = param['param']['InputFile']
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options=solveroptions
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results


def sub_network_invest(data, param, **kwargs):
    """
    Generate and solve mixed integer linear problem of the complex sub network.

    Parameters
    ----------

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.
    """
    # %% Calculate global parameters
    bwsf = calc_bwsf(
        param['param']['capital_interest'], param['param']['lifetime']
        )

    energy_system = primary_network(
        data, param, use_hp=False, return_unsolved=True
        )

    # %% Connection to primary network
    for obj in energy_system.__dict__['_nodes']:
        if obj.label == 'heat network':
            prim_hnw = obj
        if obj.label == 'electricity network':
            prim_enw = obj

    # %% Busses
    sub_enw = solph.Bus(label='sub electricity network')
    sub_hnw = solph.Bus(label='sub heat network')

    energy_system.add(sub_enw, sub_hnw)

    # %% Sources
    sub_elec_source = solph.components.Source(
        label='sub network electricity source',
        outputs={
            sub_enw: solph.flows.Flow(
                variable_costs=(
                    param['param']['elec_consumer_charges_grid']
                    + data['el_spot_price']
                    )
                )
            }
        )

    energy_system.add(sub_elec_source)

    # %% Sinks
    sub_heat_sink = solph.components.Sink(
        label='sub network heat demand',
        inputs={
            sub_hnw: solph.flows.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['sub_heat_demand'].max(),
                fix=data['sub_heat_demand']/data['sub_heat_demand'].max()
                )}
        )

    energy_system.add(sub_heat_sink)

    # %% Primary Network Heat pump
    if param['param']['use_BEW_op_bonus']:
        _, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
            data, param
            )
    else:
        bew_op_bonus_Q_in_self = 0

    for i in range(1, param['hp']['amount']+1):
        hp = solph.components.OffsetConverter(
            label=f'heat pump {i}',
            inputs={
                prim_enw: solph.flows.Flow(
                    variable_costs=param['param']['elec_consumer_charges_self'],
                )
            },
            outputs={
                prim_hnw: solph.flows.Flow(
                    variable_costs=(
                        param['hp']['op_cost_var'] - bew_op_bonus_Q_in_self
                        ),
                    investment=solph.Investment(
                        ep_costs=(
                            param['hp']['inv_spez_m'] / bwsf
                            * (1 - param['param']['BEW'])
                            ),
                        maximum=param['hp']['cap_max'],
                        minimum=param['hp']['cap_min'],
                        offset=(
                            param['hp']['inv_spez_b'] / bwsf
                            * (1 - param['param']['BEW'])
                            ),
                        nonconvex=solph.NonConvex()
                        ),
                    max=data['hp_Q_max'],
                    min=data['hp_Q_min'],
                    nonconvex=solph.NonConvex()
                    )
                },
            coefficients=[data['hp_c_0'], data['hp_c_1']]
            )

        energy_system.add(hp)

    # %% Sub Network Heat Pump
    if param['param']['use_BEW_op_bonus']:
        bew_op_bonus_Q_in = calc_bew_el_cost_sub(data, param)
    else:
        bew_op_bonus_Q_in = 0


    for i in range(1, param['sub hp']['amount']+1):
        sub_hp = solph.components.OffsetConverter(
            label=f'sub heat pump {i}',
            inputs={
                sub_enw: solph.flows.Flow()
            },
            outputs={
                sub_hnw: solph.flows.Flow(
                    variable_costs=(
                        param['sub hp']['op_cost_var'] - bew_op_bonus_Q_in
                        ),
                    investment=solph.Investment(
                        ep_costs=(
                            param['sub hp']['inv_spez_m'] / bwsf
                            * (1 - param['param']['BEW'])
                            ),
                        maximum=param['sub hp']['cap_max'],
                        minimum=param['sub hp']['cap_min'],
                        offset=(
                            param['sub hp']['inv_spez_b'] / bwsf
                            * (1 - param['param']['BEW'])
                            ),
                        nonconvex=solph.NonConvex()
                        ),
                    max=data['sub_hp_Q_max'],
                    min=data['sub_hp_Q_min'],
                    nonconvex=solph.NonConvex()
                    )
                },
            coefficients=[data['sub_hp_c_0'], data['sub_hp_c_1']]
            )

        energy_system.add(sub_hp)

    # %% Short term storage
    sub_st_tes = solph.components.GenericStorage(
        label='sub st-tes',
        investment=solph.Investment(
            ep_costs=(param['sub st-tes']['inv_spez_m'] / bwsf),
            maximum=param['sub st-tes']['cap_max'],
            minimum=param['sub st-tes']['cap_min'],
            offset=(param['sub st-tes']['inv_spez_b'] / bwsf),
            nonconvex=True
            ),
        inputs={
            sub_hnw: solph.flows.Flow(
                variable_costs=param['sub st-tes']['op_cost_var']
                )
            },
        outputs={
            sub_hnw: solph.flows.Flow(
                variable_costs=param['sub st-tes']['op_cost_var']
                )
            },
        invest_relation_input_capacity=param['sub st-tes']['Q_in_to_cap'],
        invest_relation_output_capacity=param['sub st-tes']['Q_out_to_cap'],
        initial_storage_level=param['sub st-tes']['init_storage'],
        loss_rate=param['sub st-tes']['Q_rel_loss'],
        inflow_conversion_factor=param['sub st-tes']['inflow_conv'],
        outflow_conversion_factor=param['sub st-tes']['outflow_conv'])

    energy_system.add(sub_st_tes)

    # %% Auxillary Transformer
    prim_to_sub = solph.components.Converter(
        label='primary network',
        inputs={prim_hnw: solph.flows.Flow()},
        outputs={
            sub_hnw: solph.flows.Flow(
                nominal_value=param['prim']['Q_max'],
                max=1.0,
                min=0.0
                )
            },
        conversion_factors={sub_hnw: param['prim']['eta_prim']}
        )

    energy_system.add(prim_to_sub)

    # %% Solve
    model = solph.Model(energy_system)
    # model.write('my_model.lp', io_options={'symbolic_solver_labels': True})
    solveroptions = {}
    if 'mipgap' in param['param'].keys():
        solveroptions['MIPGap'] = param['param']['mipgap']
    if 'TimeLimit' in param['param'].keys():
        solveroptions['TimeLimit'] = param['param']['TimeLimit']
    if 'MIPFocus' in param['param'].keys():
        solveroptions['MIPFocus'] = param['param']['MIPFocus']
    if 'SolverLogPath' in param['param'].keys():
        solveroptions['LogFile'] = param['param']['SolverLogPath']
    if 'ResultFile' in param['param'].keys():
        solveroptions['ResultFile'] = param['param']['ResultFile']
    if 'InputFile' in param['param'].keys():
        solveroptions['InputFile'] = param['param']['InputFile']
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options=solveroptions
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results


def IVgdh_network_invest(data, param):
    """
    Generate and solve mixed integer linear problem of the 4. generation
    district heating network.

    Parameters
    ----------

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.

    use_hp : bool
        Flag to set 'True' if a heat pump should be used in the energy system.
        (Default: 'True')

    return_unsolved : bool
        Flag to set 'True' if the energy system should be returned unsolved.
        (Default: 'False')
    """
    # %% Calculate global parameters
    bwsf = calc_bwsf(
        param['param']['capital_interest'], param['param']['lifetime']
        )

    # %% Create time index
    periods = len(data)
    date_time_index = pd.date_range(data.index[0], periods=periods, freq='h')

    # %% Create energy system
    energy_system = solph.EnergySystem(
        timeindex=date_time_index, infer_last_interval=True
        )

    # %% Busses
    bnw = solph.Bus(label='biogas network')
    enw = solph.Bus(label='electricity network')
    hnw = solph.Bus(label='heat network')

    ice_node = solph.Bus(label='ice node')
    ice_no_bonus_node = solph.Bus(label='ice no bonus node')
    spotmarket_node = solph.Bus(label='spotmarket node')

    sol_node = solph.Bus(label='solar node')

    energy_system.add(
        bnw, enw, hnw, ice_node, ice_no_bonus_node, spotmarket_node, sol_node
        )

    # %% Sources
    biogas_source = solph.components.Source(
        label='biogas source',
        outputs={
            bnw: solph.flows.Flow(
                variable_costs=(
                    data['biogas_price']
                    + data['co2_price'] * param['param']['ef_biogas']
                    )
                )
            }
        )

    # BEW operational bonus
    if param['param']['use_BEW_op_bonus']:
        bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
            data, param
            )
    else:
        bew_op_bonus_Q_in_grid = 0
        bew_op_bonus_Q_in_self = 0

    hp_P_max = (data['hp_Q_max'] - data['hp_c_0']) / data['hp_c_1']

    elec_source = solph.components.Source(
        label='electricity source',
        outputs={
            enw: solph.flows.Flow(
                variable_costs=(
                    param['param']['elec_consumer_charges_grid']
                    - param['param']['elec_consumer_charges_self']
                    + data['el_spot_price']
                    + (data['hp_Q_max'] / hp_P_max) * (
                        - bew_op_bonus_Q_in_grid
                        + bew_op_bonus_Q_in_self
                        )
                    ))}
        )

    # solar_source = solph.components.Source(
    #     label='solar thermal',
    #     outputs={
    #         hnw: solph.flows.Flow(
    #             variable_costs=(
    #                 param['sol']['op_cost_var']
    #                 - param['sol']['BEW_op']
    #                 ),
    #             nominal_value=solph.Investment(
    #                 ep_costs=(
    #                     param['sol']['inv_spez_m'] / bwsf
    #                     * (1 - param['param']['BEW'])
    #                     ),
    #                 maximum=param['sol']['cap_max'],
    #                 minimum=param['sol']['cap_min'],
    #                 offset=(
    #                     param['sol']['inv_spez_b'] / bwsf
    #                     * (1 - param['param']['BEW'])
    #                     ),
    #                 nonconvex=solph.NonConvex()
    #             ),
    #             fix=data['solar_heat_flow']
    #         )}
    #     )

    solar_source = solph.components.Source(
        label='solar source',
        outputs={sol_node: solph.flows.Flow()}
        )

    energy_system.add(biogas_source, elec_source, solar_source)

    solar_thermal = solph.components.Converter(
        label='solar thermal',
        inputs={sol_node: solph.flows.Flow()},
        outputs={
            hnw: solph.flows.Flow(
                investment=solph.Investment(
                    ep_costs=(
                        param['sol']['inv_spez_m'] / bwsf
                        * (1 - param['param']['BEW'])
                        ),
                    maximum=param['sol']['cap_max'],
                    minimum=param['sol']['cap_min'],
                    nonconvex=solph.NonConvex(),
                    offset=(
                        param['sol']['inv_spez_b'] / bwsf
                        * (1 - param['param']['BEW'])
                        )
                    ),
                max=data['solar_heat_flow'],
                min=data['solar_heat_flow'],
                variable_costs=(
                    max(param['sol']['op_cost_var'] - param['sol']['BEW_op'],
                        param['sol']['op_cost_var'] * (1 - 0.9))
                    )
                )
            },
        conversion_factors={hnw: 1}
        )

    energy_system.add(solar_thermal)

    # %% Sinks
    elec_sink = solph.components.Sink(
        label='spotmarket',
        inputs={
            spotmarket_node: solph.flows.Flow(
                variable_costs=(
                    -data['el_spot_price'] - param['param']['vNNE']
                    ))}
        )

    heat_sink = solph.components.Sink(
        label='heat demand',
        inputs={
            hnw: solph.flows.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['heat_demand'].max(),
                fix=data['heat_demand']/data['heat_demand'].max()
                )}
        )

    energy_system.add(elec_sink, heat_sink)

    # %% Heat pump
    for i in range(1, param['hp']['amount']+1):
        # Heat pump component
        hp = solph.components.OffsetConverter(
            label=f'heat pump {i}',
            inputs={
                enw: solph.flows.Flow(
                    variable_costs=(
                        param['param']['elec_consumer_charges_self'])
                    )},
            outputs={
                hnw: solph.flows.Flow(
                    variable_costs=(
                        param['hp']['op_cost_var'] - bew_op_bonus_Q_in_self
                        ),
                    investment=solph.Investment(
                        ep_costs=(
                            param['hp']['inv_spez_m'] / bwsf
                            * (1 - param['param']['BEW'])
                            ),
                        maximum=param['hp']['cap_max'],
                        minimum=param['hp']['cap_min'],
                        offset=(
                            param['hp']['inv_spez_b'] / bwsf
                            * (1 - param['param']['BEW'])
                            ),
                        nonconvex=solph.NonConvex()
                        ),
                    max=data['hp_Q_max'],
                    min=data['hp_Q_min'],
                    nonconvex=solph.NonConvex()
                    )
                },
            coefficients=[data['hp_c_0'], data['hp_c_1']]
            )

        energy_system.add(hp)

    # %% Internal extraction engine
    ice = solph.components.Converter(
        label='ice',
        inputs={
            bnw: solph.flows.Flow()
            },
        outputs={
            ice_node: solph.flows.Flow(
                variable_costs=param['ice']['op_cost_var']
                ),
            hnw: solph.flows.Flow(
                investment=solph.Investment(
                    ep_costs=(
                        param['ice']['inv_spez'] / bwsf
                        * (1 - param['param']['BEW'])
                        ),
                    maximum=param['ice']['cap_max'],
                    minimum=param['ice']['cap_min'],
                    nonconvex=solph.NonConvex()
                    ),
                max=(data['ice_H_max']*data['ice_eta_th']),
                min=(data['ice_H_min']*data['ice_eta_th']),
                nonconvex=solph.NonConvex()
                )
            },
        conversion_factors={
            ice_node: data['ice_eta_el'],
            hnw: data['ice_eta_th']
            }
        )

    energy_system.add(ice)

    # %% Storage
    s_tes = solph.components.GenericStorage(
        label='s-tes',
        investment=solph.Investment(
            ep_costs=(param['s-tes']['inv_spez_m'] / bwsf),
            maximum=param['s-tes']['cap_max'],
            minimum=param['s-tes']['cap_min'],
            offset=(param['s-tes']['inv_spez_b'] / bwsf),
            nonconvex=True
            ),
        inputs={
            hnw: solph.flows.Flow(
                nominal_value=param['s-tes']['Q_in'],
                variable_costs=param['s-tes']['op_cost_var']
                )
            },
        outputs={
            hnw: solph.flows.Flow(
                nominal_value=param['s-tes']['Q_out'],
                variable_costs=param['s-tes']['op_cost_var']
                )
            },
        initial_storage_level=param['s-tes']['init_storage'],
        loss_rate=param['s-tes']['Q_rel_loss'],
        inflow_conversion_factor=param['s-tes']['inflow_conv'],
        outflow_conversion_factor=param['s-tes']['outflow_conv'])

    energy_system.add(s_tes)

    # %% Auxillary components
    ice_P_N = (
        (data['heat_demand'].max() * 1/3)
        / data['ice_eta_th'].mean()
        * data['ice_eta_el'].mean()
        )
    ice_chp_bonus = param['param']['chp_bonus']

    ice_with_chp_bonus = solph.components.Converter(
        label='ice with chp bonus',
        inputs={ice_node: solph.flows.Flow()},
        outputs={
            spotmarket_node: solph.flows.Flow(
                nominal_value=ice_P_N,
                max=1.0,
                min=0.0,
                full_load_time_max=param['param']['h_max_chp_bonus'],
                variable_costs=(
                    -ice_chp_bonus - param['param']['TEHG_bonus'])
                )},
        conversion_factors={enw: 1}
        )

    ice_no_chp_bonus = solph.components.Converter(
        label='ice no chp bonus',
        inputs={ice_node: solph.flows.Flow()},
        outputs={ice_no_bonus_node: solph.flows.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={ice_no_bonus_node: 1}
        )

    ice_no_chp_bonus_int = solph.components.Converter(
        label='ice no chp bonus internally',
        inputs={ice_no_bonus_node: solph.Flow()},
        outputs={enw: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={enw: 1}
        )

    ice_no_chp_bonus_ext = solph.components.Converter(
        label='ice no chp bonus externally',
        inputs={ice_no_bonus_node: solph.Flow()},
        outputs={spotmarket_node: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={spotmarket_node: 1}
        )

    energy_system.add(
        ice_with_chp_bonus, ice_no_chp_bonus,
        ice_no_chp_bonus_int, ice_no_chp_bonus_ext
        )

    # %% Solve
    model = solph.Model(energy_system)
    # model.write('my_model.lp', io_options={'symbolic_solver_labels': True})
    solveroptions = {}
    if 'mipgap' in param['param'].keys():
        solveroptions['MIPGap'] = param['param']['mipgap']
    if 'TimeLimit' in param['param'].keys():
        solveroptions['TimeLimit'] = param['param']['TimeLimit']
    if 'MIPFocus' in param['param'].keys():
        solveroptions['MIPFocus'] = param['param']['MIPFocus']
    if 'SolverLogPath' in param['param'].keys():
        solveroptions['LogFile'] = param['param']['SolverLogPath']
    if 'ResultFile' in param['param'].keys():
        solveroptions['ResultFile'] = param['param']['ResultFile']
    if 'InputFile' in param['param'].keys():
        solveroptions['InputFile'] = param['param']['InputFile']
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options=solveroptions
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results
