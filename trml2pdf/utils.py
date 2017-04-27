# trml2pdf - An RML to PDF converter
# Copyright (C) 2003, Fabien Pinckaers, UCL, FSA
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import re

import reportlab
from six import text_type


def text_get(node):
    rc = node.text
    for node in node.getchildren():
        rc += node.text
    return rc

units = [
    (re.compile('^(-?[0-9\.]+)\s*in$'), reportlab.lib.units.inch),
    (re.compile('^(-?[0-9\.]+)\s*cm$'), reportlab.lib.units.cm),
    (re.compile('^(-?[0-9\.]+)\s*mm$'), reportlab.lib.units.mm),
    (re.compile('^(-?[0-9\.]+)\s*pt$'), 1),
    (re.compile('^(-?[0-9\.]+)\s*$'), 1),
]


def unit_get(size):
    result = None
    for unit in units:
        res = unit[0].search(size, 0)
        if res:
            result = unit[1] * float(res.group(1))
    if result is None:
        if size.upper() == 'NONE':
            result = None
        else:
            result = size
    return result


def tuple_int_get(node, attr_name, default=None):
    if attr_name not in node.attrib:
        return default
    res = tuple(int(x) for x in node.attrib[attr_name].split(','))
    return res


def bool_get(value):
    return (str(value) == "1") or (value.lower() == 'yes')


def attr_get(node, attrs, attrs_dict={}):
    res = {}
    for name in attrs:
        if name in node.attrib:
            res[name] = unit_get(node.attrib[name])
    for key in attrs_dict:
        if key in node.attrib:
            if attrs_dict[key] == 'str':
                res[key] = text_type(node.attrib[key])
            elif attrs_dict[key] == 'bool':
                res[key] = bool_get(node.attrib[key])
            elif attrs_dict[key] == 'int':
                res[key] = int(node.attrib[key])
            elif attrs_dict[key] == 'float':
                res[key] = float(node.attrib[key])
    return res
