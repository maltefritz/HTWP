# -*- coding: utf-8 -*-
"""
Created on Tue Jan 18 14:52:10 2022

@author: Malte Fritz & Jonas Freißmann
"""

from tespy.components import (
    CycleCloser, Source, Sink, Pump, HeatExchanger, Condenser,
    HeatExchangerSimple, Compressor, Valve
    )
from tespy.connections import Connection
from tespy.networks import Network

# %% Network
nw = Network(
    fluids=['water', 'air', 'NH3'],
    T_unit='C', p_unit='bar', h_unit='kJ / kg', m_unit='kg / s'
    )

# %% Components

# Low Pressure Cycle
cycle_closer_lp = CycleCloser('Refrigerant Cycle Closer LP')

# Heat Source
heatsource_feedflow = Source('Heat Source Feed Flow')
heatsource_pump = Pump('Heat Source Recirculation Pump')
heatsource_heatexchanger = HeatExchanger('Heat Source Heat Exchanger')
heatsource_backflow = Sink('Heat Source Back Flow')

# Compression
compressor_lp = Compressor('Compressor LP')

# Expansion
valve_lp = Valve('Expansion Valve LP')

# Intermediate Heat Exchanger
intermediate_heatexchanger = HeatExchanger('Intermediate Heat Exchanger')

# High Pressure Cycle
cycle_closer_hp = CycleCloser('Refrigerant Cycle Closer HP')

# Heat Sink
cons_backflow = Source('Consumer Back Flow')
cons_pump = Pump('Heat Sink Recirculation Pump')
condenser = Condenser('Heat Sink Condenser')
cons_heatsink = HeatExchangerSimple('Heat Consumer')
cons_feedflow = Sink('Consumer Feed Flow')

# Compression
compressor_hp = Compressor('Compressor HP')

# Expansion
valve_hp = Valve('Expansion Valve HP')

# %% Connections

# Low Pressure Cycle
# Heat Source
cc_lp2hs_heatex = Connection(
    cycle_closer_lp, 'out1', heatsource_heatexchanger, 'in2', label='con01'
    )
hs_feed2hs_pump = Connection(
    heatsource_feedflow, 'out1', heatsource_pump, 'in1', label='con02'
    )
hs_pump2hs_heatex = Connection(
    heatsource_pump, 'out1', heatsource_heatexchanger, 'in1', label='con03'
    )
hs_heatex2hs_back = Connection(
    heatsource_heatexchanger, 'out1', heatsource_backflow, 'in1', label='con04'
    )

nw.add_conns(
    cc_lp2hs_heatex, hs_feed2hs_pump, hs_pump2hs_heatex, hs_heatex2hs_back
    )

# Compression LP
hs_heatex2comp_lp = Connection(
    heatsource_heatexchanger, 'out2', compressor_lp, 'in1', label='con05'
    )
comp_lp2intermed_heatex = Connection(
    compressor_lp, 'out1', intermediate_heatexchanger, 'in1', label='con06'
    )

nw.add_conns(hs_heatex2comp_lp, comp_lp2intermed_heatex)

# Expansion LP
intermed_heatex2valve_lp = Connection(
    intermediate_heatexchanger, 'out1', valve_lp, 'in1', label='con07'
    )
valve_lp2cc_lp = Connection(
    valve_lp, 'out1', cycle_closer_lp, 'in1', label='con08'
    )

nw.add_conns(intermed_heatex2valve_lp, valve_lp2cc_lp)

# High Pressure Cycle
cc_hp2intermed_heatex = Connection(
    cycle_closer_hp, 'out1', intermediate_heatexchanger, 'in2', label='con09'
    )

nw.add_conns(cc_hp2intermed_heatex)

# Compression LP
intermed_heatex2comp_hp = Connection(
    intermediate_heatexchanger, 'out2', compressor_hp, 'in1', label='con10'
    )
comp_hp2cond = Connection(
    compressor_hp, 'out1', condenser, 'in1', label='con11'
    )

nw.add_conns(intermed_heatex2comp_hp, comp_hp2cond)

# Heat Sink
cons_back2cons_pump = Connection(
    cons_backflow, 'out1', cons_pump, 'in1', label='con12'
    )
cons_pump2cond = Connection(
    cons_pump, 'out1', condenser, 'in2', label='con13'
    )
cond2cons_hs = Connection(
    condenser, 'out2', cons_heatsink, 'in1', label='con14'
    )
cons_hs2cons_feed = Connection(
    cons_heatsink, 'out1', cons_feedflow, 'in1', label='con15'
    )

nw.add_conns(
    cons_back2cons_pump, cons_pump2cond, cond2cons_hs, cons_hs2cons_feed
    )

# Expansion HP
cond2valve_hp = Connection(
    condenser, 'out1', valve_hp, 'in1', label='con16'
    )
valve_hp2cc_hp = Connection(
    valve_hp, 'out1', cycle_closer_hp, 'in1', label='con17'
    )

nw.add_conns(cond2valve_hp, valve_hp2cc_hp)
