# -*- coding: utf-8 -*-
"""
Created on Tue Jan 18 14:52:10 2022

@author: Malte Fritz & Jonas Freißmann
"""

from tespy.components import (
    CycleCloser, Source, Sink, Pump, HeatExchanger, Condenser,
    HeatExchangerSimple, Compressor, Valve
    )
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

# Heat Sink
cons_backflow = Source('Consumer Back Flow')
condenser = Condenser('Heat Sink Condenser')
cons_heatsink = HeatExchangerSimple('Heat Consumer')
cons_pump = Pump('Heat Source Recirculation Pump')
cons_feedflow = Sink('Consumer Feed Flow')

# Compression
compressor = Compressor('Compressor')

# Expansion
valve = Valve('Expansion Valve')
