# -*- coding: utf-8 -*-
"""
Created on Tue Jan 18 14:52:10 2022

@author: Malte Fritz & Jonas Freißmann
"""

from tespy.components import (
    CycleCloser, Source, Sink
    )
from tespy.networks import Network

# %% Network
nw = Network(
    fluids=['water', 'air', 'NH3'],
    T_unit='C', p_unit='bar', h_unit='kJ / kg', m_unit='kg / s'
    )

# %% Components
# Sources and Sinks
cycle_closer = CycleCloser('Refrigerant Cycle Closer')

cons_backflow = Source('Consumer Back Flow')
cons_feedflow = Sink('Consumer Feed Flow')

heatsource_feedflow = Source('Heat Source Feed Flow')
heatsource_backflow = Sink('Heat Source Back Flow')
