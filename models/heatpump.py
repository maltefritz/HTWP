# -*- coding: utf-8 -*-
"""
Generic heat pump model.

@author: Jonas Freißmann and Malte Fritz
"""

from tespy.components import (
    CycleCloser, Source, Sink, Pump, HeatExchanger, Condenser,
    HeatExchangerSimple, Compressor, Valve
    )
from tespy.connections import Connection
from tespy.networks import Network


class Heatpump():
    """
    Generic heat pump model.

    Parameters
    ----------
    fluids : list
        list containing all fluids in the heat pump topology

    nr_cycles : int
        number of cycles/stages of the heat pump

    int_heatex : dict
        dictionary where each key is the integer index of the cycle of the hot
        side of an internal heat exchanger and the value is either a single
        integer for the cycle of the cold side or a list when multiple
        internal heat exchangers have the hot side of the cycle of the key

    intercooler : dict
        dictionary where each key is the integer index of the cycle in which
        the intercooler(s) are to be placed and where the corresponding value
        is a dictionary with the keys 'amount' (the number of compression
        stages is this number + 1) and 'type' (either 'HeatExchanger' or
        'HeatExchangerSimple')

    kwargs
        currently supported kwargs are the units used for displaying results
        with TESPy (T_unit, p_unit, h_unit and m_unit; see TESPy documentation)

    Note
    ----
    Both for the internal heat exchangers and the intercoolers an integer
    index is used to refer to a cycle/stage of a heatpump. This allows the
    distinct positioning of these components under the premiss that they are
    always placed in certain positions within their respective cycles. For
    intercoolers between compression stages this is trivial, but the internal
    heat exchangers place has to be predeterment for ease of use. From what
    could be gathered from literature these internal heat exchangers are
    used to cool the condensate and preheat the evaporated refrigerant most of
    the time, so this will be the implementation within the model.
    The nomenclature of integer indexes of cycles is also used in the
    labelling of the components.
    """

    def __init__(self, fluids, nr_cycles=1, int_heatex={}, intercooler={},
                 **kwargs):
        self.fluids = fluids
        self.nr_cycles = nr_cycles
        self.int_heatex = int_heatex
        self.intercooler = intercooler

        self.init_network(**kwargs)
        self.components = dict()
        self.generate_components()
        self.connections = dict()
        self.generate_topology()

    def init_network(self, **kwargs):
        """Initialize network."""
        if 'T_unit' in kwargs:
            T_unit = kwargs['T_unit']
        else:
            T_unit = 'C'
        if 'p_unit' in kwargs:
            p_unit = kwargs['p_unit']
        else:
            p_unit = 'bar'
        if 'h_unit' in kwargs:
            h_unit = kwargs['h_unit']
        else:
            h_unit = 'kJ / kg'
        if 'm_unit' in kwargs:
            m_unit = kwargs['m_unit']
        else:
            m_unit = 'kg / s'

        self.nw = Network(
            fluids=self.fluids, T_unit=T_unit, p_unit=p_unit, h_unit=h_unit,
            m_unit=m_unit
            )

    def generate_components(self):
        """Generate necessary components based on topology parametrisation."""
        # Heat Source Feed Flow
        self.components['Heat Source Feed Flow'] = Source(
            'Heat Source Feed Flow'
            )

        # Heat Source Back Flow
        self.components['Heat Source Back Flow'] = Sink(
            'Heat Source Back Flow'
            )

        # Heat Source Recirculation Pump
        self.components['Heat Source Recirculation Pump'] = Pump(
            'Heat Source Recirculation Pump'
            )

        # Heat Source evaporator
        self.components['Evaporator 1'] = HeatExchanger('Evaporator 1')

        # Consumer Cycle Closer
        self.components['Consumer Cycle Closer'] = CycleCloser(
            'Consumer Cycle Closer'
            )

        # Consumer Recirculation Pump
        self.components['Consumer Recirculation Pump'] = Pump(
            'Consumer Recirculation Pump'
            )

        # Consumer
        self.components['Consumer'] = HeatExchangerSimple('Consumer')

        for cycle in range(1, self.nr_cycles+1):
            # Cycle closer for each cycle
            self.components[f'Cycle Closer {cycle}'] = CycleCloser(
                f'Cycle Closer {cycle}'
                )

            # Valve for each cycle
            self.components[f'Valve {cycle}'] = Valve(f'Valve {cycle}')

            if cycle != 1:
                # Heat exchanger between each cycle
                self.components[f'Heat Exchanger {cycle-1}_{cycle}'] = (
                    HeatExchanger(f'Heat Exchanger {cycle-1}_{cycle}')
                    )

            if cycle == self.nr_cycles:
                # Condenser in the upper most cycle
                self.components[f'Condenser {cycle}'] = Condenser(
                    f'Condenser {cycle}'
                    )

            # Intercoolers where they are placed by user
            if cycle in self.intercooler.keys():
                nr_intercooler = self.intercooler[cycle]['amount']
                ic_type = self.intercooler[cycle]['type']
                for i in range(1, nr_intercooler+2):
                    if i < nr_intercooler+1:
                        if ic_type == 'HeatExchanger':
                            self.components[f'Intercooler {cycle}-{i}'] = (
                                HeatExchanger(f'Intercooler {cycle}-{i}')
                                )
                        elif ic_type == 'HeatExchangerSimple':
                            self.components[f'Intercooler {cycle}-{i}'] = (
                                HeatExchangerSimple(f'Intercooler {cycle}-{i}')
                                )

                    # Necessary amount of compressors due to intercoolers
                    self.components[f'Compressor {cycle}-{i}'] = Compressor(
                        f'Compressor {cycle}_{i}'
                        )
            else:
                # Single compressors for each cycle without intercooler
                self.components[f'Compressor {cycle}'] = Compressor(
                        f'Compressor {cycle}'
                        )

            if cycle in self.int_heatex.keys():
                if type(self.int_heatex[cycle]) == list:
                    for target_cycle in self.int_heatex[cycle]:
                        label = (
                            f'Internal Heat Exchanger {cycle}_{target_cycle}'
                            )
                        self.components[label] = HeatExchanger(label)
                else:
                    label = (
                        'Internal Heat Exchanger '
                        + f'{cycle}_{self.int_heatex[cycle]}'
                        )
                    self.components[label] = HeatExchanger(label)

    def generate_topology(self):
        """Generate the heat pump topology based on defined components."""
        self.set_conn(
            'valve1_to_evaporator1',
            'Valve 1', 'out1',
            'Evaporator 1', 'in2'
            )

        self.set_conn(
            f'heatsource_ff_to_heatsource_pump',
            'Heat Source Feed Flow', 'out1',
            'Heat Source Recirculation Pump', 'in1'
            )
        self.set_conn(
            'heatsource_pump_to_evaporator1',
            'Heat Source Recirculation Pump', 'out1',
            'Evaporator 1', 'in1'
            )
        self.set_conn(
            'evaporator1_to_heatsource_bf',
            'Evaporator 1', 'out1',
            'Heat Source Back Flow', 'in1'
            )

        self.set_conn(
            f'heatsink_cc_to_heatsink_pump',
            'Consumer Cycle Closer', 'out1',
            'Consumer Recirculation Pump', 'in1'
            )
        self.set_conn(
            f'heatsink_pump_to_cond{self.nr_cycles}',
            'Consumer Recirculation Pump', 'out1',
            f'Condenser {self.nr_cycles}', 'in2'
            )
        self.set_conn(
            f'cond{self.nr_cycles}_to_consumer',
            f'Condenser {self.nr_cycles}', 'out2',
            'Consumer', 'in1'
            )
        self.set_conn(
            'consumer_to_heatsink_cc',
            'Consumer', 'out1',
            'Consumer Cycle Closer', 'in1'
            )

        for cycle in range(1, self.nr_cycles+1):
            self.set_conn(
                f'cc{cycle}_to_valve{cycle}',
                f'Cycle Closer {cycle}', 'out1',
                f'Valve {cycle}', 'in1'
                )

            if cycle != 1:
                self.set_conn(
                   f'valve{cycle}_to_heat_ex{cycle-1}_{cycle}',
                   f'Valve {cycle}', 'out1',
                   f'Heat Exchanger {cycle-1}_{cycle}', 'in2'
                   )

            cycle_int_heatex = list()
            for i in range(1, self.nr_cycles+1):
                if i in self.int_heatex:
                    if type(self.int_heatex[i]) == int:
                        if self.int_heatex[i] == cycle:
                            cycle_int_heatex.append(i)
                    elif type(self.int_heatex[i]) == list:
                        if cycle in self.int_heatex[i]:
                            cycle_int_heatex.append(i)

            last_int_heatex = ''
            for c_int_heatex in cycle_int_heatex:
                if not last_int_heatex:
                    if cycle == 1:
                        self.set_conn(
                            (f'evaporator{cycle}_to_'
                             + f'int_heatex{c_int_heatex}_{cycle}'),
                            f'Evaporator 1', 'out2',
                            f'Internal Heat Exchanger {c_int_heatex}_{cycle}',
                            'in2'
                            )
                    else:
                        self.set_conn(
                            (f'heatex{cycle-1}_{cycle}_to_'
                             + f'int_heatex{c_int_heatex}_{cycle}'),
                            f'Heat Exchanger {cycle-1}_{cycle}', 'out2',
                            f'Internal Heat Exchanger {c_int_heatex}_{cycle}',
                            'in2'
                            )
                else:
                    self.set_conn(
                        (f'int_heatex{last_int_heatex}_{cycle}'
                         + f'_to_int_heatex{c_int_heatex}_{cycle}'),
                        f'Internal Heat Exchanger {last_int_heatex}_{cycle}',
                        'out2',
                        f'Internal Heat Exchanger {c_int_heatex}_{cycle}',
                        'in2'
                        )
                last_int_heatex = c_int_heatex

            if cycle in self.intercooler:
                if not last_int_heatex:
                    if cycle == 1:
                        self.set_conn(
                            f'evaporator1_to_comp{cycle}-1',
                            f'Evaporator 1', 'out2',
                            f'Compressor {cycle}-1', 'in1'
                            )
                    else:
                        self.set_conn(
                            f'heatex{cycle-1}_{cycle}_to_comp{cycle}',
                            f'Heat Exchanger {cycle-1}_{cycle}', 'out2',
                            f'Compressor {cycle}-1', 'in1'
                            )
                else:
                    self.set_conn(
                        f'int_heatex{last_int_heatex}_{cycle}_to_comp{cycle}',
                        f'Internal Heat Exchanger {last_int_heatex}_{cycle}',
                        'out2',
                        f'Compressor {cycle}-1', 'in1'
                        )
                for i in range(1, self.intercooler[cycle]['amount']+1):
                    self.set_conn(
                        f'comp{cycle}-{i}_to_intercooler{cycle}-{i}',
                        f'Compressor {cycle}-{i}', 'out1',
                        f'Intercooler {cycle}-{i}', 'in1'
                        )
                    self.set_conn(
                        f'intercooler{cycle}-{i}_to_comp{cycle}-{i+1}',
                        f'Intercooler {cycle}-{i}', 'out1',
                        f'Compressor {cycle}-{i+1}', 'in1'
                        )
                if cycle == self.nr_cycles:
                    self.set_conn(
                        (f'comp{cycle}-{self.intercooler[cycle]["amount"]+1}'
                         + f'_to_cond{cycle}'),
                        (f'Compressor {cycle}'
                         + f'-{self.intercooler[cycle]["amount"]+1}'),
                        'out1',
                        f'Condenser {cycle}', 'in1'
                        )
                else:
                    self.set_conn(
                        (f'comp{cycle}-{self.intercooler[cycle]["amount"]+1}'
                         + f'_to_heatex{cycle}_{cycle+1}'),
                        (f'Compressor {cycle}'
                         + f'-{self.intercooler[cycle]["amount"]+1}'),
                        'out1',
                        f'Heat Exchanger {cycle}_{cycle+1}', 'in1'
                        )

            else:
                if not last_int_heatex:
                    if cycle == 1:
                        self.set_conn(
                            f'evaporator1_to_comp{cycle}',
                            f'Evaporator 1', 'out2',
                            f'Compressor {cycle}', 'in1'
                            )
                    else:
                        self.set_conn(
                            f'heatex{cycle-1}_{cycle}_to_comp{cycle}',
                            f'Heat Exchanger {cycle-1}_{cycle}', 'out2',
                            f'Compressor {cycle}', 'in1'
                            )
                else:
                    self.set_conn(
                        f'int_heatex{last_int_heatex}_{cycle}_to_comp{cycle}',
                        f'Internal Heat Exchanger {last_int_heatex}_{cycle}',
                        'out2',
                        f'Compressor {cycle}', 'in1'
                        )
                if cycle == self.nr_cycles:
                    self.set_conn(
                        f'comp{cycle}_to_cond{cycle}',
                        f'Compressor {cycle}', 'out1',
                        f'Condenser {cycle}', 'in1'
                        )
                else:
                    self.set_conn(
                        f'comp{cycle}_to_heatex{cycle}_{cycle+1}',
                        f'Compressor {cycle}', 'out1',
                        f'Heat Exchanger {cycle}_{cycle+1}', 'in1'
                        )

            int_heatexs = [
                comp for comp in self.components
                if f'Internal Heat Exchanger {cycle}' in comp
                ]
            int_heatexs.sort(reverse=True)
            last_int_heatex = ''
            for int_heatex in int_heatexs:
                int_heatex_idx = int_heatex.split(' ')[-1]
                if not last_int_heatex:
                    if cycle == self.nr_cycles:
                        self.set_conn(
                            f'cond{cycle}_to_int_heatex{int_heatex_idx}',
                            f'Condenser {cycle}', 'out1',
                            int_heatex, 'in1'
                            )
                    else:
                        self.set_conn(
                            (f'heatex{cycle}_{cycle+1}'
                             + f'_to_int_heatex{int_heatex_idx}'),
                            f'Heat Exchanger {cycle}_{cycle+1}', 'out1',
                            int_heatex, 'in1'
                            )
                else:
                    last_int_heatex_idx = last_int_heatex.split(' ')[-1]
                    self.set_conn(
                        (f'int_heatex{last_int_heatex_idx}'
                         + f'_to_int_heatex{int_heatex_idx}'),
                        last_int_heatex, 'out1',
                        int_heatex, 'in1'
                        )
                last_int_heatex = int_heatex

            if not last_int_heatex:
                if cycle == self.nr_cycles:
                    self.set_conn(
                        f'cond{cycle}_to_cc{cycle}',
                        f'Condenser {cycle}', 'out1',
                        f'Cycle Closer {cycle}', 'in1'
                        )
                else:
                    self.set_conn(
                        f'heatex{cycle}_{cycle+1}_to_cc{cycle}',
                        f'Heat Exchanger {cycle}_{cycle+1}', 'out1',
                        f'Cycle Closer {cycle}', 'in1'
                        )
            else:
                last_int_heatex_idx = last_int_heatex.split(' ')[-1]
                self.set_conn(
                    f'int_heatex{last_int_heatex_idx}_to_cc{cycle}',
                    last_int_heatex, 'out1',
                    f'Cycle Closer {cycle}', 'in1'
                    )

    def set_conn(self, label, comp_out, outlet, comp_in, inlet):
        """
        Set connections between components.

        Parameters
        ----------
        label : str
            name of connection (also used as label attribute within the
            generated TESPy object)

        comp_out : tespy.components.component.Component
            component from which the connection originates

        outlet : str
            name of outlet of comp_out (e.g. 'out1')

        comp_in : tespy.components.component.Component
            component where the connection terminates

        inlet : str
            name of inlet of comp_in (e.g. 'in1')
        """
        self.connections[label] = Connection(
            self.components[comp_out], outlet,
            self.components[comp_in], inlet,
            label=label
            )
        self.nw.add_conns(self.connections[label])

    def delete_component(self, component):
        """
        Delete component and all associated connections from Heatpump.

        Parameters
        ----------
        component : str
            label of component to be deleted
        """
        if component not in self.components.keys():
            print(f'No component with label {component} found.')
            return

        del self.components[component]
        print(f'Component {component} succesfully deleted from Heatpump.')

        connections_copy = self.connections.copy()

        for label, connection in self.connections.items():
            is_source = component == connection.source.label
            is_target = component == connection.target.label
            if is_source or is_target:
                self.nw.del_conns(connection)
                del connections_copy[label]
                print(f'Connection {label} succesfully deleted from Heatpump.')

        self.connections = connections_copy


if __name__ == '__main__':
    hp = Heatpump(
        ['water', 'NH3'], nr_cycles=2, int_heatex={2: [1, 2]},
        intercooler={1: {'amount': 2, 'type': 'HeatExchanger'}}
        )
