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
cycle_closer = CycleCloser('Refrigerant Cycle Closer')

# Heat Source
heatsource_feedflow = Source('Heat Source Feed Flow')
heatsource_pump = Pump('Heat Source Recirculation Pump')
heatsource_heatexchanger = HeatExchanger('Heat Source Heat Exchanger')
heatsource_backflow = Sink('Heat Source Back Flow')

# Compression
compressor = Compressor('Compressor')

# Heat Sink
cons_backflow = Source('Consumer Back Flow')
cons_pump = Pump('Heat Source Recirculation Pump')
condenser = Condenser('Heat Sink Condenser')
cons_heatsink = HeatExchangerSimple('Heat Consumer')
cons_feedflow = Sink('Consumer Feed Flow')

# Expansion
valve = Valve('Expansion Valve')

# %% Connections
# Heat Source
cc2hs_heatex = Connection(
    cycle_closer, 'out1', heatsource_heatexchanger, 'in2', label='con01'
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
    cc2hs_heatex, hs_feed2hs_pump, hs_pump2hs_heatex, hs_heatex2hs_back
    )

# Compression
hs_heatex2comp = Connection(
    heatsource_heatexchanger, 'out2', compressor, 'in1', label='con05'
    )
comp2cond = Connection(
    compressor, 'out1', condenser, 'in1', label='con06'
    )

nw.add_conns(hs_heatex2comp, comp2cond)

# Heat Sink
cons_back2cons_pump = Connection(
    cons_backflow, 'out1', cons_pump, 'in1', label='con07'
    )
cons_pump2cond = Connection(
    cons_pump, 'out1', condenser, 'in2', label='con08'
    )
cond2cons_hs = Connection(
    condenser, 'out2', cons_heatsink, 'in1', label='con09'
    )
cons_hs2cons_feed = Connection(
    cons_heatsink, 'out1', cons_feedflow, 'in1', label='con10'
    )

nw.add_conns(
    cons_back2cons_pump, cons_pump2cond, cond2cons_hs, cons_hs2cons_feed
    )

# Expansion
cond2valve = Connection(
    condenser, 'out1', valve, 'in1', label='con11'
    )
valve2cc = Connection(
    valve, 'out1', cycle_closer, 'in1', label='con12'
    )

nw.add_conns(cond2valve, valve2cc)
