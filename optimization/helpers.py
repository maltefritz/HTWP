from eco_funcs import bew_op_bonus


def calc_bew_el_cost_prim(data, param):
    hp_P_max = (data['hp_Q_max'] - data['hp_c_0']) / data['hp_c_1']
    SCOP = data['hp_Q_max'].mean() / hp_P_max.mean()
    if SCOP >= 2.5:
        bew_op_bonus_Q_in = (
            bew_op_bonus(SCOP, el_source_type='conventional')
            * (data['hp_Q_max']-hp_P_max)/data['hp_Q_max']
            )
    else:
        bew_op_bonus_Q_in = 0

    el_cost_per_Q_out_grid = (
        (data['el_spot_price']+param['param']['elec_consumer_charges_grid'])
        / (data['hp_Q_max'] / hp_P_max)
        )
    el_cost_per_Q_out_self = (
        param['param']['elec_consumer_charges_self']
        / (data['hp_Q_max'] / hp_P_max)
        )

    bew_op_bonus_Q_in_grid = bew_op_bonus_Q_in.copy()
    bew_op_bonus_Q_in_self = bew_op_bonus_Q_in.copy()

    for idx in bew_op_bonus_Q_in.index:
        bew_op_bonus_Q_in_grid[idx] = min(
            bew_op_bonus_Q_in_grid[idx],
            max(0, 0.9*el_cost_per_Q_out_grid[idx])
            )
        bew_op_bonus_Q_in_self[idx] = min(
            bew_op_bonus_Q_in_self[idx],
            max(0, 0.9*el_cost_per_Q_out_self[idx])
            )

    return bew_op_bonus_Q_in_grid, bew_op_bonus_Q_in_self

def calc_bew_el_cost_sub(data, param):
    sub_hp_P_max = (data['sub_hp_Q_max'] - data['sub_hp_c_0']) / data['sub_hp_c_1']
    SCOP = data['sub_hp_Q_max'].mean() / sub_hp_P_max.mean()
    if SCOP >= 2.5:
        bew_op_bonus_Q_in = (
            bew_op_bonus(SCOP, el_source_type='conventional')
            * (data['sub_hp_Q_max']-sub_hp_P_max)/data['sub_hp_Q_max']
            )
    else:
        bew_op_bonus_Q_in = 0

    el_cost_per_Q_out = (
        (data['el_spot_price']+param['param']['elec_consumer_charges_grid'])
        / (data['sub_hp_Q_max'] / sub_hp_P_max)
        )

    for idx in bew_op_bonus_Q_in.copy().index:
        bew_op_bonus_Q_in[idx] = min(
            bew_op_bonus_Q_in[idx],
            max(0, 0.9*el_cost_per_Q_out[idx])
            )

    return bew_op_bonus_Q_in
