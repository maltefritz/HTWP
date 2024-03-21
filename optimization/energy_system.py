# -*- coding: utf-8 -*-

import oemof.solph as solph
import pandas as pd
from eco_funcs import bew_op_bonus, chp_bonus
from helpers import calc_bew_el_cost_prim, calc_bew_el_cost_sub


def primary_network(data, param, use_hp=True, return_unsolved=False):
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
    # %% Create time index
    periods = len(data)
    date_time_index = pd.date_range(data.index[0], periods=periods, freq='h')

    # %% Create energy system
    energy_system = solph.EnergySystem(
        timeindex=date_time_index, infer_last_interval=True
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
            gnw: solph.Flow(
                variable_costs=(
                    data['gas_price']
                    + (data['co2_price'] * param['param']['ef_gas'])
                    ))}
        )

    try:
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
    except KeyError:
        elec_source_cost = (
            param['param']['elec_consumer_charges_grid']
            - param['param']['elec_consumer_charges_self']
            + data['el_spot_price']
            )

    elec_source = solph.components.Source(
        label='electricity source',
        outputs={
            enw: solph.Flow(
                variable_costs=elec_source_cost
                )
            }
        )

    energy_system.add(gas_source, elec_source)

    # %% Sinks
    elec_sink = solph.components.Sink(
        label='spotmarket',
        inputs={
            spotmarket_node: solph.Flow(
                variable_costs=(
                    -data['el_spot_price'] - param['param']['vNNE']
                    ))}
        )

    heat_sink = solph.components.Sink(
        label='heat demand',
        inputs={
            hnw: solph.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['heat_demand'].max(),
                fix=data['heat_demand']/data['heat_demand'].max()
                )}
        )

    energy_system.add(elec_sink, heat_sink)

    # %% Heat pump
    if use_hp:
        for i, Q_N_hp in enumerate(param['hp']['Q_Ns'].values()):
            # Heat pump component
            hp = solph.components.OffsetConverter(
                label=f'heat pump {i+1}',
                inputs={
                    enw: solph.Flow(
                        variable_costs=(
                            param['param']['elec_consumer_charges_self'])
                        )},
                outputs={
                    hnw: solph.Flow(
                        nominal_value=1,
                        max=Q_N_hp*data['hp_Q_max'],
                        min=Q_N_hp*data['hp_Q_min'],
                        variable_costs=(
                            param['hp']['op_cost_var']
                            - bew_op_bonus_Q_in_self
                            ),
                        nonconvex=solph.NonConvex()
                        )
                    },
                coefficients=[Q_N_hp*data['hp_c_0'], data['hp_c_1']]
                )

            energy_system.add(hp)

    # %% Combined cycle extraction turbine
    # ccet = solph.components.GenericCHP(
    #     label='ccet',
    #     fuel_input={
    #         gnw: solph.Flow(
    #             custom_attributes={
    #                 'H_L_FG_share_max': data['ccet_H_L_FG_share_max'].tolist()
    #                 },
    #             nominal_value=data['ccet_Q_in'].mean()
    #             )},
    #     electrical_output={
    #         ccet_node: solph.Flow(
    #             variable_costs=param['ccet']['op_cost_var'],
    #             custom_attributes={
    #                 'P_max_woDH': data['ccet_P_max_woDH'].tolist(),
    #                 'P_min_woDH': data['ccet_P_min_woDH'].tolist(),
    #                 'Eta_el_max_woDH': data['ccet_eta_el_max'].tolist(),
    #                 'Eta_el_min_woDH': data['ccet_eta_el_min'].tolist()
    #                 }
    #             )},
    #     heat_output={
    #         hnw: solph.Flow(
    #             custom_attributes={'Q_CW_min': data['ccet_Q_CW_min'].tolist()}
    #             )},
    #     beta=data['ccet_beta'].tolist(),
    #     back_pressure=False
    #     )

    # energy_system.add(ccet)

    ccet = solph.components.Converter(
        label='ccet',
        inputs={gnw: solph.flows.Flow()},
        outputs={
            ccet_node: solph.flows.Flow(
                variable_costs=param['ccet']['op_cost_var']
                ),
            hnw: solph.flows.Flow(
                nominal_value=param['ccet']['Q_N'],
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

    # %% Peak load boiler
    plb = solph.components.Converter(
        label='peak load boiler',
        inputs={gnw: solph.Flow()},
        outputs={
            hnw: solph.Flow(
                nominal_value=param['plb']['Q_N'],
                max=1,
                min=0,
                variable_costs=(
                    param['plb']['op_cost_var']
                    + param['param']['energy_tax'])
                )},
        conversion_factors={hnw: param['plb']['eta']}
        )

    energy_system.add(plb)

    # %% Short term storage
    st_tes = solph.components.GenericStorage(
        label='st-tes',
        nominal_storage_capacity=param['st-tes']['Q'],
        inputs={
            hnw: solph.Flow(
                nominal_value=param['st-tes']['Q_N_in'],
                max=param['st-tes']['Q_rel_in_max'],
                min=param['st-tes']['Q_rel_in_min'],
                variable_costs=param['st-tes']['op_cost_var'],
                nonconvex=solph.NonConvex()
                )},
        outputs={
            hnw: solph.Flow(
                nominal_value=param['st-tes']['Q_N_out'],
                max=param['st-tes']['Q_rel_out_max'],
                min=param['st-tes']['Q_rel_out_min'],
                nonconvex=solph.NonConvex())},
        initial_storage_level=param['st-tes']['init_storage'],
        loss_rate=param['st-tes']['Q_rel_loss'],
        inflow_conversion_factor=param['st-tes']['inflow_conv'],
        outflow_conversion_factor=param['st-tes']['outflow_conv'])

    energy_system.add(st_tes)

    # %% Auxillary components
    ccet_P_N = data['ccet_P_max_woDH'].mean()
    ccet_chp_bonus = chp_bonus(ccet_P_N * 1e3, use_case='grid') * 10
    ccet_with_chp_bonus = solph.components.Converter(
        label='ccet with chp bonus',
        inputs={ccet_node: solph.Flow()},
        outputs={
            spotmarket_node: solph.Flow(
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
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options={"mipgap": param['param']['mipgap']}
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results


def sub_network(data, param, **kwargs):
    """
    Generate and solve mixed integer linear problem of the complex sub network.

    Parameters
    ----------

    data : pandas.DataFrame
        csv file of user defined time dependent parameters.

    param : dict
        JSON parameter file of user defined constants.
    """
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
            sub_enw: solph.Flow(
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
            sub_hnw: solph.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['sub_heat_demand'].max(),
                fix=data['sub_heat_demand']/data['sub_heat_demand'].max()
                )}
        )

    energy_system.add(sub_heat_sink)

    # %% Heat pumps

    # %% Primary Network Heat pump
    _, bew_op_bonus_Q_in_self = calc_bew_el_cost_prim(
        data, param
        )

    # Heat pump component
    for i, Q_N_hp in enumerate(param['hp']['Q_Ns'].values()):
        hp = solph.components.OffsetConverter(
            label=f'heat pump {i+1}',
            inputs={
                prim_enw: solph.Flow()
                },
            outputs={
                prim_hnw: solph.Flow(
                    nominal_value=1,
                    max=Q_N_hp*data['hp_Q_max'],
                    min=Q_N_hp*data['hp_Q_min'],
                    variable_costs=(
                        param['hp']['op_cost_var']
                        - bew_op_bonus_Q_in_self
                        ),
                    nonconvex=solph.NonConvex()
                    )
                },
            coefficients=[Q_N_hp*data['hp_c_0'], data['hp_c_1']]
            )

        energy_system.add(hp)

    # %% Sub Network Heat pump
    bew_op_bonus_Q_in = calc_bew_el_cost_sub(data, param)

    # Heat pump component
    for i, Q_N_hp in enumerate(param['sub hp']['Q_Ns'].values()):
        sub_hp = solph.components.OffsetConverter(
            label=f'sub heat pump {i+1}',
            inputs={
                sub_enw: solph.Flow()
                },
            outputs={
                sub_hnw: solph.Flow(
                    nominal_value=1,
                    max=Q_N_hp*data['sub_hp_Q_max'],
                    min=Q_N_hp*data['sub_hp_Q_min'],
                    variable_costs=(
                        param['sub hp']['op_cost_var']
                        - bew_op_bonus_Q_in
                        ),
                    nonconvex=solph.NonConvex()
                    )
                },
            coefficients=[Q_N_hp*data['sub_hp_c_0'], data['sub_hp_c_1']]
            )

        energy_system.add(sub_hp)

    # %% Short term storage
    sub_st_tes = solph.components.GenericStorage(
        label='sub st-tes',
        nominal_storage_capacity=param['sub st-tes']['Q'],
        inputs={
            sub_hnw: solph.Flow(
                nominal_value=param['sub st-tes']['Q_N_in'],
                max=param['sub st-tes']['Q_rel_in_max'],
                min=param['sub st-tes']['Q_rel_in_min'],
                variable_costs=param['sub st-tes']['op_cost_var'],
                nonconvex=solph.NonConvex()
                )
            },
        outputs={
            sub_hnw: solph.Flow(
                nominal_value=param['sub st-tes']['Q_N_out'],
                max=param['sub st-tes']['Q_rel_out_max'],
                min=param['sub st-tes']['Q_rel_out_min'],
                nonconvex=solph.NonConvex()
                )
            },
        initial_storage_level=param['sub st-tes']['init_storage'],
        loss_rate=param['sub st-tes']['Q_rel_loss'],
        inflow_conversion_factor=param['sub st-tes']['inflow_conv'],
        outflow_conversion_factor=param['sub st-tes']['outflow_conv'])

    energy_system.add(sub_st_tes)

    # %% Auxillary Converter
    prim_to_sub = solph.components.Converter(
        label='primary network',
        inputs={prim_hnw: solph.Flow()},
        outputs={
            sub_hnw: solph.Flow(
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
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options={"mipgap": param['param']['mipgap']}
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results


def sonderborg_network(data, param, use_hp=True, return_unsolved=False):
    """
    Generate and solve mixed integer linear problem of district heating network
    of Sonderborg.

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
    # %% Create time index
    periods = len(data)
    date_time_index = pd.date_range(data.index[0], periods=periods, freq='h')

    # %% Create energy system
    energy_system = solph.EnergySystem(timeindex=date_time_index)

    # %% Busses
    gnw = solph.Bus(label='gas network')
    enw = solph.Bus(label='electricity network')
    hnw = solph.Bus(label='heat network')

    ice_node = solph.Bus(label='ice node')
    spotmarket_node = solph.Bus(label='spotmarket node')

    energy_system.add(gnw, enw, hnw, ice_node, spotmarket_node)

    # %% Sources
    gas_source = solph.components.Source(
        label='gas source',
        outputs={
            gnw: solph.Flow(
                variable_costs=(
                    data['gas_price']
                    + (data['co2_price'] * param['param']['ef_gas'])
                    ))}
        )

    elec_source = solph.components.Source(
        label='electricity source',
        outputs={
            enw: solph.Flow(
                variable_costs=(
                    param['param']['elec_consumer_charges_grid']
                    - param['param']['elec_consumer_charges_self']
                    + data['el_spot_price']
                    # + (data['co2_price'] * data['ef_om'])
                    ))}
        )

    energy_system.add(gas_source, elec_source)

    # %% Sinks
    elec_sink = solph.components.Sink(
        label='spotmarket',
        inputs={
            spotmarket_node: solph.Flow(
                variable_costs=(
                    -data['el_spot_price'] - param['param']['vNNE']
                    ))}
        )

    heat_sink = solph.components.Sink(
        label='heat demand',
        inputs={
            hnw: solph.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['heat_demand'].max(),
                fix=data['heat_demand']/data['heat_demand'].max()
                )}
        )

    energy_system.add(elec_sink, heat_sink)

    # %% Heat pump
    if use_hp:
        hp = solph.components.OffsetConverter(
            label='heat pump',
            inputs={
                enw: solph.Flow(
                    nominal_value=1,
                    max=data['hp_P_max'],
                    min=data['hp_P_min'],
                    variable_costs=(
                        param['param']['elec_consumer_charges_self']),
                    nonconvex=solph.NonConvex()
                    )},
            outputs={
                hnw: solph.Flow(
                    variable_costs=(
                        param['hp']['op_cost_var'])
                    )},
            coefficients=[data['hp_c_0'], data['hp_c_1']]
            )

        energy_system.add(hp)

    # %% Combined cycle extraction turbine
    ice = solph.components.GenericCHP(
        label='ice',
        fuel_input={
            gnw: solph.Flow(
                H_L_FG_share_max=data['ice_H_L_FG_share_max'].tolist(),
                H_L_FG_share_min=data['ice_H_L_FG_share_min'].tolist(),
                nominal_value=data['ice_Q_in'].mean()
                )},
        electrical_output={
            ice_node: solph.Flow(
                variable_costs=param['ice']['op_cost_var'],
                P_max_woDH=data['ice_P_max_woDH'].tolist(),
                P_min_woDH=data['ice_P_min_woDH'].tolist(),
                Eta_el_max_woDH=data['ice_eta_el_max'].tolist(),
                Eta_el_min_woDH=data['ice_eta_el_min'].tolist()
                )},
        heat_output={
            hnw: solph.Flow(
                Q_CW_min=[0 for p in range(0, periods)],
                Q_CW_max=[0 for p in range(0, periods)]
                )},
        Beta=[0 for p in range(0, periods)],
        back_pressure=False
        )

    energy_system.add(ice)

    # %% Peak load boiler
    plb = solph.components.Converter(
        label='peak load boiler',
        inputs={gnw: solph.Flow()},
        outputs={
            hnw: solph.Flow(
                nominal_value=param['plb']['Q_N'],
                max=1,
                min=0,
                variable_costs=(
                    param['plb']['op_cost_var']
                    + param['param']['energy_tax'])
                )},
        conversion_factors={hnw: param['plb']['eta']}
        )

    energy_system.add(plb)

    # %% Auxillary components
    ice_P_N = data['ice_P_max_woDH'].mean()
    ice_chp_bonus = chp_bonus(ice_P_N * 1e3, use_case='grid') * 10
    ice_with_chp_bonus = solph.components.Converter(
        label='ice with chp bonus',
        inputs={ice_node: solph.Flow()},
        outputs={
            spotmarket_node: solph.Flow(
                nominal_value=ice_P_N,
                max=1.0,
                min=0.0,
                summed_max=param['param']['h_max_chp_bonus'],
                variable_costs=(
                    -ice_chp_bonus - param['param']['TEHG_bonus'])
                )},
        conversion_factors={enw: 1}
        )

    ice_no_chp_bonus = solph.components.Converter(
        label='ice no chp bonus',
        inputs={ice_node: solph.Flow()},
        outputs={enw: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={enw: 1}
        )

    enw_to_spotmarket = solph.components.Converter(
        label='enw to spotmarket',
        inputs={enw: solph.Flow()},
        outputs={
            spotmarket_node: solph.Flow(
                nominal_value=9999,
                max=1.0,
                min=0.0
                )},
        conversion_factors={spotmarket_node: 1}
        )

    energy_system.add(ice_with_chp_bonus, ice_no_chp_bonus, enw_to_spotmarket)

    # %% Return unsolved
    if return_unsolved:
        return energy_system

    # %% Solve
    model = solph.Model(energy_system)
    solph.constraints.limit_active_flow_count_by_keyword(
        model, 'storageflowlimit', lower_limit=0, upper_limit=1)
    # model.write('my_model.lp', io_options={'symbolic_solver_labels': True})
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options={"mipgap": param['param']['mipgap']}
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results


def IVgdh_network(data, param, return_unsolved=False):
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
    spotmarket_node = solph.Bus(label='spotmarket node')

    energy_system.add(bnw, enw, hnw, ice_node, spotmarket_node)

    # %% Sources
    biogas_source = solph.components.Source(
        label='biogas source',
        outputs={
            bnw: solph.Flow(
                variable_costs=(data['biogas_price'])
                )}
        )

    elec_source = solph.components.Source(
        label='electricity source',
        outputs={
            enw: solph.Flow(
                variable_costs=(
                    param['param']['elec_consumer_charges_grid']
                    - param['param']['elec_consumer_charges_self']
                    + data['el_spot_price']
                    ))}
        )

    solar_source = solph.components.Source(
        label='solar thermal',
        outputs={
            hnw: solph.Flow(
                nominal_value=param['sol']['A'],     # Vllt auch A?
                variable_costs=(
                    param['sol']['op_cost_var']
                    - param['sol']['BEW_op']
                ),
                fix=data['solar_heat_flow']
            )}
        )

    energy_system.add(biogas_source, elec_source, solar_source)

    # %% Sinks
    elec_sink = solph.components.Sink(
        label='spotmarket',
        inputs={
            spotmarket_node: solph.Flow(
                variable_costs=(
                    -data['el_spot_price'] - param['param']['vNNE']
                    ))}
        )

    heat_sink = solph.components.Sink(
        label='heat demand',
        inputs={
            hnw: solph.Flow(
                variable_costs=-param['param']['heat_price'],
                nominal_value=data['heat_demand'].max(),
                fix=data['heat_demand']/data['heat_demand'].max()
                )}
        )

    energy_system.add(elec_sink, heat_sink)

    # %% Heat pump
    for i, Q_N_hp in enumerate(param['hp']['Q_Ns'].values()):
        # BEW operational bonus
        hp_P_max = (data['hp_Q_max'] - data['hp_c_0']) / data['hp_c_1']
        SCOP = data['hp_Q_max'].mean() / hp_P_max.mean()
        if SCOP >= 2.5:
            bew_op_bonus_Q_in = (
                bew_op_bonus(SCOP, el_source_type='conventional')
                * (data['hp_Q_max']-hp_P_max)/data['hp_Q_max']
                )
        else:
            bew_op_bonus_Q_in = 0

        el_cost_per_Q_out = (
            (data['el_spot_price']+param['param']['elec_consumer_charges_self'])
            / (data['hp_Q_max'] / hp_P_max)
            )

        for idx in bew_op_bonus_Q_in.copy().index:
            bew_op_bonus_Q_in[idx] = min(
                bew_op_bonus_Q_in[idx],
                max(0, 0.9*el_cost_per_Q_out[idx])
                )

        # Heat pump component
        hp = solph.components.OffsetConverter(
            label=f'heat pump {i+1}',
            inputs={
                enw: solph.Flow(
                    variable_costs=(
                        param['param']['elec_consumer_charges_self'])
                    )},
            outputs={
                hnw: solph.Flow(
                    nominal_value=1,
                    max=Q_N_hp*data['hp_Q_max'],
                    min=Q_N_hp*data['hp_Q_min'],
                    variable_costs=(
                        param['hp']['op_cost_var']
                        - bew_op_bonus_Q_in
                        ),
                    nonconvex=solph.NonConvex()
                    )
                },
            coefficients=[Q_N_hp*data['hp_c_0'], data['hp_c_1']]
            )

        energy_system.add(hp)

    # %% Internal extraction engine
    ice = solph.components.GenericCHP(
        label='ice',
        fuel_input={
            bnw: solph.Flow(
                custom_attributes={
                    'H_L_FG_share_max': data['ice_H_L_FG_share_max'].tolist(),
                    'H_L_FG_share_min': data['ice_H_L_FG_share_min'].tolist()
                    },
                nominal_value=data['ice_Q_in'].mean()
                )},
        electrical_output={
            ice_node: solph.Flow(
                variable_costs=param['ice']['op_cost_var'],
                custom_attributes={
                    'P_max_woDH': data['ice_P_max_woDH'].tolist(),
                    'P_min_woDH': data['ice_P_min_woDH'].tolist(),
                    'Eta_el_max_woDH': data['ice_eta_el_max'].tolist(),
                    'Eta_el_min_woDH': data['ice_eta_el_min'].tolist()
                    }
                )},
        heat_output={
            hnw: solph.Flow(
                custom_attributes={
                    'Q_CW_min': data['ice_Q_CW_min'].tolist(),
                    'Q_CW_max': data['ice_Q_CW_max'].tolist()
                    }
                )},
        beta=data['ice_beta'].tolist(),
        back_pressure=False
        )

    energy_system.add(ice)

    # %% Storage
    s_tes = solph.components.GenericStorage(
        label='s-tes',
        nominal_storage_capacity=param['s-tes']['Q'],
        inputs={
            hnw: solph.Flow(
                nominal_value=param['s-tes']['Q_N_in'],
                max=param['s-tes']['Q_rel_in_max'],
                min=param['s-tes']['Q_rel_in_min'],
                variable_costs=param['s-tes']['op_cost_var'],
                nonconvex=solph.NonConvex()
                )},
        outputs={
            hnw: solph.Flow(
                nominal_value=param['s-tes']['Q_N_out'],
                max=param['s-tes']['Q_rel_out_max'],
                min=param['s-tes']['Q_rel_out_min'],
                nonconvex=solph.NonConvex())},
        initial_storage_level=param['s-tes']['init_storage'],
        loss_rate=param['s-tes']['Q_rel_loss'],
        inflow_conversion_factor=param['s-tes']['inflow_conv'],
        outflow_conversion_factor=param['s-tes']['outflow_conv'])

    energy_system.add(s_tes)

    # %% Auxillary components
    ice_P_N = data['ice_P_max_woDH'].mean()
    ice_chp_bonus = chp_bonus(ice_P_N * 1e3, use_case='grid') * 10
    ice_with_chp_bonus = solph.components.Converter(
        label='ice with chp bonus',
        inputs={ice_node: solph.Flow()},
        outputs={
            spotmarket_node: solph.Flow(
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
        inputs={ice_node: solph.Flow()},
        outputs={enw: solph.Flow(
            nominal_value=9999,
            max=1.0,
            min=0.0
            )},
        conversion_factors={enw: 1}
        )

    enw_to_spotmarket = solph.components.Converter(
        label='enw to spotmarket',
        inputs={enw: solph.Flow()},
        outputs={
            spotmarket_node: solph.Flow(
                nominal_value=9999,
                max=1.0,
                min=0.0
                )},
        conversion_factors={spotmarket_node: 1}
        )

    energy_system.add(ice_with_chp_bonus, ice_no_chp_bonus, enw_to_spotmarket)

    # %% Return unsolved
    if return_unsolved:
        return energy_system

    # %% Solve
    model = solph.Model(energy_system)
    # model.write('my_model.lp', io_options={'symbolic_solver_labels': True})
    model.solve(
        solver='gurobi', solve_kwargs={'tee': True},
        cmdline_options={"mipgap": param['param']['mipgap']}
        )

    # Ergebnisse in results
    results = solph.processing.results(model)

    # Metaergebnisse
    meta_results = solph.processing.meta_results(model)

    return results, meta_results

