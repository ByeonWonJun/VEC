# Eclipse SUMO, Simulation of Urban MObility; see https://eclipse.org/sumo
# Copyright (C) 2008-2021 German Aerospace Center (DLR) and others.
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# https://www.eclipse.org/legal/epl-2.0/
# This Source Code may also be made available under the following Secondary
# Licenses when the conditions for such availability set forth in the Eclipse
# Public License 2.0 are satisfied: GNU General Public License, version 2
# or later which is available at
# https://www.gnu.org/licenses/old-licenses/gpl-2.0-standalone.html
# SPDX-License-Identifier: EPL-2.0 OR GPL-2.0-or-later

# This file is a port of createVehTypeDistribution.py to sumolib

# @file    __init__.py
# @author  Mirko Barthauer (Technische Universitaet Braunschweig, Institut fuer Verkehr und Stadtbauwesen)
# @author  Jakob Erdmann
# @author  Michael Behrisch
# @author  Maxwell Schrader
# @date    2016-06-09 (createVehTypeDistribution)
# @date    2021-07-19 (refractor to sumolib)

import os
import sys
import re
from typing import Any, List, Tuple, Union
import xml.dom.minidom
import random
from sumolib.files.additional import write_additional_minidom

"""
Creates a vehicle type distribution with a number of representative car-following parameter sets.
"""


class _FixDistribution(object):

    def __init__(self, params, isNumeric=True):
        if isNumeric:
            self._params = tuple([float(p) for p in params])
        else:
            self._params = params
        self._limits = (0, None)
        self._isNumeric = isNumeric
        self._maxSampleAttempts = 10

    def setMaxSamplingAttempts(self, n):
        if n is not None:
            self._maxSampleAttempts = n

    def setLimits(self, limits):
        self._limits = limits

    def sampleValue(self):
        if self._isNumeric:
            value = None
            nrSampleAttempts = 0
            # Sample until value falls into limits
            while nrSampleAttempts < self._maxSampleAttempts \
                    and (value is None or (self._limits[1] is not None and value > self._limits[1]) or
                         (self._limits[0] is not None and value < self._limits[0])):
                value = self._sampleValue()
                nrSampleAttempts += 1
            # Eventually apply fallback cutting value to limits
            if self._limits[0] is not None and value < self._limits[0]:
                value = self._limits[0]
            elif self._limits[1] is not None and value > self._limits[1]:
                value = self._limits[1]
        else:
            value = self._sampleValue()
        return value

    def sampleValueString(self, decimalPlaces):
        if self._isNumeric:
            decimalPattern = "%." + str(decimalPlaces) + "f"
            return decimalPattern % self.sampleValue()
        return self.sampleValue()

    def _sampleValue(self):
        return self._params[0]


class _NormalDistribution(_FixDistribution):

    def __init__(self, mu, sd):
        _FixDistribution.__init__(self, (mu, sd))

    def _sampleValue(self):
        return random.normalvariate(self._params[0], self._params[1])


class _LogNormalDistribution(_FixDistribution):

    def __init__(self, mu, sd):
        _FixDistribution.__init__(self, (mu, sd))

    def _sampleValue(self):
        return random.lognormvariate(self._params[0], self._params[1])


class _NormalCappedDistribution(_FixDistribution):

    def __init__(self, mu, sd, min, max):
        _FixDistribution.__init__(self, (mu, sd, min, max))
        if mu < min or mu > max:
            sys.stderr.write("mean %s is outside cutoff bounds [%s, %s]" % (
                mu, min, max))
            sys.exit()

    def _sampleValue(self):
        while True:
            cand = random.normalvariate(self._params[0], self._params[1])
            if cand >= self._params[2] and cand <= self._params[3]:
                return cand


class _UniformDistribution(_FixDistribution):

    def __init__(self, a, b):
        _FixDistribution.__init__(self, (a, b))

    def _sampleValue(self):
        return random.uniform(self._params[0], self._params[1])


class _GammaDistribution(_FixDistribution):

    def __init__(self, alpha, beta):
        _FixDistribution.__init__(self, (alpha, 1.0 / beta))

    def _sampleValue(self):
        return random.gammavariate(self._params[0], self._params[1])


_DIST_DICT = {
    'normal': _NormalDistribution,
    'lognormal': _LogNormalDistribution,
    'normalCapped': _NormalCappedDistribution,
    'uniform': _UniformDistribution,
    'gamma': _GammaDistribution
}


class VehAttribute:

    def __init__(self, name: str, is_param: bool = False, distribution: str = None, distribution_params: Union[dict, Any] = None, bounds: tuple = None, attribute_value: str = None) -> None:
        """
        This emmulates one line of example config.txt in 
            https://sumo.dlr.de/docs/Tools/Misc.html#createvehtypedistributionpy 
        Either distribution or attribute_value should be populated
        Args:
            name (str): the name of the attribute. Examples: "tau", "sigma", "length"
            is_param (bool, optional): is the attribute a parameter that should be added as a child element. Defaults to False
            distribution (str, optional): the name of the distribution to use ()
            distribution_params (Union[dict, Any], optional): the parameters corresponding to the distribution
            bounds (tuple, optional): the bounds of the distribution. Defaults to None.
            attribute_value (str, optional): if no distribution is given, parameter should be. the injects the attribute name and attribute value in every vehType. Defaults to None
        """
        self.is_param = is_param
        self.name = name
        self.distribution = distribution
        self.distribution_params = distribution_params
        self.bounds = bounds
        self.attribute_value = attribute_value
        if self.attribute_value and self.distribution:
            sys.exit(
                "Only one of distribution or attribute value should be defined, not both")
        self.d_obj = self._dist_helper(
            distribution, distribution_params, bounds)

    def _dist_helper(self, distribution, dist_params, dist_bounds) -> Union[None, _FixDistribution]:
        if distribution:
            try:
                d = _DIST_DICT[distribution](**dist_params)
                d.setLimits(dist_bounds) if dist_bounds else d.setLimits(
                    (0, None))
            except KeyError:
                sys.exit(
                    f"The distribution {distribution} is not known. Please select on of: \n" + "\n".join(list(_DIST_DICT.keys())))
        else:
            isNumeric = False if self.name == "emissionClass" else len(
                re.findall(r'^(-?[0-9]+(\.[0-9]+)?)$', self.attribute_value)) > 0
            d = _FixDistribution((self.attribute_value, ), isNumeric)
        return d

    def add_sampling_attempts(self, attempts):
        if self.d_obj:
            self.d_obj.setMaxSamplingAttempts(attempts)


class CreateVehTypeDistribution:

    def __init__(self, seed: int = 42, size: int = 100, name: str = 'vehDist', resampling: int = 100, decimal_places: int = 3) -> None:
        """
        Creates a VehicleType Distribution. See https://sumo.dlr.de/docs/Definition_of_Vehicles%2C_Vehicle_Types%2C_and_Routes.html#vehicle_type_distributions

        Args:
            seed (int, optional): random seed. Defaults to 42.
            size (int, optional): number of vTypes in the distribution. Defaults to 100.
            name (str, optional): alphanumerical ID used for the created vehicle type distribution. Defaults to 'vehDist'.
            resampling (int, optional): number of attempts to resample a value until it lies in the specified bounds. Defaults to 100.
            decimal_places (int, optional): number of decimal places. Defaults to 3
        """
        self.seed = seed
        self.size = size
        self.name = name
        self.resampling = resampling
        self.decimal_places = decimal_places
        self.attributes: List[VehAttribute] = []

    def add_attribute(self, attribute: Union[VehAttribute, dict],):
        """
        Add an instance of the attribute class to the Parameters. Pass the sampling attempts "global" parameter
        Args:
            attribute (VehAttribute or dict): Should be either an instance of VehAttribute or a dictionary to be passed to VehAttribute instance
        """
        attribute = attribute if isinstance(attribute, VehAttribute) else VehAttribute(**attribute)
        attribute.add_sampling_attempts(self.resampling)
        self.attributes.append(attribute)

    def create_veh_dist(self, xml_dom: xml.dom.minidom.Document) -> xml.dom.minidom.Element:
        # create the vehicleDist node
        vtype_dist_node = xml_dom.createElement("vTypeDistribution")
        vtype_dist_node.setAttribute("id", self.name)

        # create the vehicle types
        for i in range(self.size):
            veh_type_node = xml_dom.createElement("vType")
            veh_type_node.setAttribute("id", self.name + str(i))
            self._generate_vehType(xml_dom, veh_type_node)
            vtype_dist_node.appendChild(veh_type_node)

        return vtype_dist_node

    def to_xml(self, file_path) -> None:

        xml_dom, existing_file = self._check_existing(file_path)

        vtype_dist_node = self.create_veh_dist(xml_dom)

        if existing_file:
            self._handle_existing(xml_dom, vtype_dist_node)
            with open(file_path, 'w') as f:
                dom_string = xml_dom.toprettyxml()
                # super annoying but this makes re-writing the xml a little bit prettier
                f.write(os.linesep.join([s for s in dom_string.splitlines() if s.strip()]))
        else:
            write_additional_minidom(xml_dom, vtype_dist_node, file_path=file_path)
        sys.stdout.write("Output written to %s" % file_path)

    def _handle_existing(self, xml_dom: xml.dom.minidom.Document, veh_dist_node: xml.dom.minidom.Element) -> None:
        existingDistNodes = xml_dom.getElementsByTagName("vTypeDistribution")
        replaceNode = None
        for existingDistNode in existingDistNodes:
            if existingDistNode.hasAttribute("id") and existingDistNode.getAttribute("id") == self.name:
                replaceNode = existingDistNode
                break
        if replaceNode is not None:
            replaceNode.parentNode.replaceChild(veh_dist_node, replaceNode)
        else:
            xml_dom.documentElement.appendChild(veh_dist_node)

    def _generate_vehType(self, xml_dom: xml.dom.minidom.Document, veh_type_node: xml.dom.minidom.Element) -> xml.dom.minidom.Node:
        for attr in self.attributes:
            if attr.is_param:
                param_node = xml_dom.createElement("param")
                param_node.setAttribute("key", attr.name)
                param_node.setAttribute(
                    "value", attr.d_obj.sampleValueString(self.decimal_places))
                veh_type_node.appendChild(param_node)
            else:
                veh_type_node.setAttribute(
                    attr.name, attr.d_obj.sampleValueString(self.decimal_places))

    @staticmethod
    def _check_existing(file_path: str) -> Tuple[xml.dom.minidom.Document, bool]:
        if os.path.exists(file_path):
            try:
                return xml.dom.minidom.parse(file_path), True
            except Exception as e:
                sys.exit("Cannot parse existing %s. Error: %s" %
                         (file_path, str(e)))
        else:
            return xml.dom.minidom.Document(), False

    def save_myself(self, file_path: str) -> None:
        """
        This function saves the class to a json format. Used for logging simulation inputs  

        Args:
            file_path (str): path to save json to
        """
        import json

        with open(file_path, "w") as f:
            f.write(
                json.dumps(
                    self,
                    default=lambda o: {
                        key: param for key, param in o.__dict__.items() if '_' not in key[0]},
                    sort_keys=True,
                    indent=4,
                )
            )


class CreateMultiVehTypeDistributions(CreateVehTypeDistribution):

    def __init__(self, ) -> None:

        self.distributions: List[CreateVehTypeDistribution] = []

    def register_veh_type_distribution(self, veh_type_dist: Union[dict, CreateVehTypeDistribution], veh_attributes: List[Union[dict, VehAttribute]]) -> None:
        
        veh_type_dist = veh_type_dist if isinstance(veh_type_dist, CreateVehTypeDistribution) else CreateVehTypeDistribution(**veh_type_dist)
        
        for attr in veh_attributes: 
            veh_type_dist.add_attribute(attr if isinstance(attr, VehAttribute) else VehAttribute(**attr))

        self.distributions.append(veh_type_dist)

    def write_xml(self, file_path):
        """
        This function will overwrite existing files

        Args:
            file_path (str): Path to the file to write to
        """
        
        xml_dom, _ = self._check_existing(file_path)

        veh_dist_nodes = [dist.create_veh_dist(xml_dom=xml_dom) for dist in self.distributions]

        write_additional_minidom(xml_dom, veh_dist_nodes, file_path=file_path)
        

# if __name__ == "__main__":

#     for i in range(3):
#         d = CreateVehTypeDistribution(seed=42, size=300, name=f"testDist{i}", resampling=50, decimal_places=3)
#         params = [{'name': "tau", 'distribution': 'uniform', 'distribution_params': {'a': 0.8, 'b': 0.1}},
#                 {'name': "sigma", 'distribution': 'lognormal', 'distribution_params': {'mu': 0.5, 'sd': 0.2}},
#                 {'name': "length", 'distribution': 'normalCapped', 'distribution_params': {'mu': 4.9, 'sd': 0.2, "max": 8, "min": 0}},
#                 {'name': "myCustomParameter", "is_param": True, 'distribution': 'gamma', 'distribution_params': {'alpha': 0.5, 'beta': 0.2}, 'bounds': (0, 12)},
#                 {'name': "vClass", 'attribute_value': 'small_car'},
#                 {'name': "carFollowModel", 'attribute_value': 'Krauss'},
#         ]

#         for param in params:
#             d.add_attribute(param)

#         d.to_xml("test.xml")
#         d.save_myself("test.json")


#     params = []
#     dists = []
#     for i in range(3):

#         dists.append(dict(seed=i, size=int((i + 1) * 50), name=f"testDist{i}", resampling=50, decimal_places=3))


#         params.append([{'name': "tau", 'distribution': 'uniform', 'distribution_params': {'a': 0.8, 'b': 0.1}},
#                 {'name': "sigma", 'distribution': 'lognormal', 'distribution_params': {'mu': 0.5, 'sd': 0.2}},
#                 {'name': "length", 'distribution': 'normalCapped', 'distribution_params': {'mu': 4.9, 'sd': 0.2, "max": 8, "min": 0}},
#                 {'name': "myCustomParameter", "is_param": True, 'distribution': 'gamma', 'distribution_params': {'alpha': 0.5, 'beta': 0.2}, 'bounds': (0, 12)},
#                 {'name': "vClass", 'attribute_value': 'small_car'},
#                 {'name': "carFollowModel", 'attribute_value': 'Krauss'},
#         ])

#     c = CreateMultiVehTypeDistributions()
#     for dist, param_list in zip(dists, params): 
#         c.register_veh_type_distribution(veh_type_dist=dist, veh_attributes=param_list)
    
#     c.write_xml("test2.xml")
#     c.save_myself("test2.json")


