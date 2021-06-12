"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

For PATCH
  * Is writable
  * Any path is present in MAPPING[resource]
  * The type agrees with that in IsAt

For PUT (if implemented)
  * Everything for PATCH
  * All entries in MAPPING[resource] are present in the supplied data
"""

from typing import Optional, Union, get_args  # get_origin, get_type_hints

# t = Union[int, float]
# isinstance(2, t)
#   TypeError: Subscripted generics cannot be used with class and instance checks
# get_args(t)
#   (<class 'int'>, <class 'float'>)
# get_origin(t)
#   typing.Union
# isinstance(2, get_args(t))
#   True

from pyDE1.de1.exceptions import DE1APIAttributeError, DE1APITypeError
from pyDE1.dispatcher.resource import Resource
from pyDE1.dispatcher.mapping import MAPPING, IsAt


def validate_patch(resource: Resource, patch: dict):
    _validate_patch_inner(patch=patch,
                          mapping=MAPPING[resource],
                          path='')


def _validate_patch_inner(patch: dict, mapping: dict, path: str):


    for key, new_value in patch.items():

        if path and len(path):
            this_path = f"{path}:{key}"
        else:
            this_path = key

        try:
            mapping_value = mapping[key]
        except KeyError:
            raise DE1APIAttributeError(f"No mapping found for {this_path}")

        if isinstance(mapping_value, dict):
            _validate_patch_inner(
                patch=patch[key],
                mapping=mapping_value,
                path=this_path,
            )

        else:
            if not isinstance(mapping_value, IsAt):
                raise DE1APITypeError(
                    f"Expected an IsAt for {this_path}:, not {mapping_value}")

            if mapping_value.read_only:
                raise DE1APIAttributeError(f"Unable to write {this_path}:")

            # Check the value type
            # This will be a simple type, or something like Union, Optional
            # https://docs.python.org/3/library/typing.html#typing.get_args
            # get_args(a_simple_type) -> None

            # TODO: typing.ForwardRef -- For example, List["SomeClass"]
            #       NB: generic types such as list["SomeClass"]
            #       will not be implicitly transformed

            type_tuple = get_args(mapping_value.v_type)
            if len(type_tuple) == 0:
                type_tuple = (mapping_value.v_type,)
            if float in type_tuple and int not in type_tuple:
                # Accept an int for a float
                type_tuple = (*type_tuple, int,)

            if not isinstance(new_value, type_tuple):
                raise DE1APITypeError(
                    f"Expected {mapping_value.v_type} value at {this_path}:, "
                    f"not {new_value}"
                )
