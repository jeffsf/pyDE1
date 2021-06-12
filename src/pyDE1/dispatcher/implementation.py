"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

# TODO: Can't read a device if is is not connected
#       need a "resource temporarily unavailable" exception

# TODO: Wipe cached state on disconnect

import asyncio
import copy
import importlib.metadata as im
import inspect
import logging
import math  # for nan to be uniquely math.nan
import sys
import time

from typing import Optional, Union

from pyDE1.de1.ble import CUUID
from pyDE1.de1.notifications import NotificationState
from pyDE1.utils import fix_enums
from pyDE1.utils_public import rgetattr, rsetattr

from pyDE1.dispatcher.resource import Resource
from pyDE1.dispatcher.mapping import MAPPING, IsAt

from pyDE1.de1 import DE1
from pyDE1.scale import Scale
from pyDE1.scale.processor import ScaleProcessor
from pyDE1.flow_sequencer import FlowSequencer
from pyDE1.de1.c_api import PackedAttr, ShotSettings, SetTime, \
    Versions, FWVersion, MMR0x80LowAddr, WaterLevels, WriteToMMR, \
    pack_one_mmr0x80_write, ReadFromMMR
from pyDE1.de1.exceptions import DE1APITypeError, DE1APIValueError, \
    DE1APIAttributeError, DE1APIKeyError
from pyDE1.dispatcher.mapping import IsAt

logger = logging.getLogger('APIImpl')

# If true, don't output nodes that have no value (write-only)
# or are empty dicts
# Otherwise math.nan fills in for the missing value
PRUNE_EMPTY_NODES = False


async def _value_to_property_setter(prop, value):

    if inspect.isroutine(prop):
        if inspect.iscoroutinefunction(prop):
            retval = await prop(value)
        else:
            retval = prop(value)
    else:
        raise DE1APITypeError (f"Setter {prop} is not an executable")

    return retval


# NB: This assumes that the MMR and CUUID are kept up to date
#     and that those that are read don't change on their own

async def _get_isat_value(isat: IsAt, flow_sequencer: FlowSequencer):

    # TODO: if IsAt.use_getter is enabled in the future, changes needed here

    target = isat.target
    attr_path = isat.attr_path
    if attr_path is None:
        raise DE1APIAttributeError(f"Write-only attribute {isat.__repr__()}")

    de1 = flow_sequencer.de1
    scale = flow_sequencer.scale_processor.scale

    retval = None

    # For any attribute or property with a getter, getattr() "just works"
    # NB: property methords should not be coroutine functions

    if target is DE1:
        retval = rgetattr(de1, attr_path)

    elif target is FlowSequencer:
        retval = rgetattr(flow_sequencer, attr_path)

    elif target is Scale:
        retval = rgetattr(scale, attr_path)

    elif isinstance(target, MMR0x80LowAddr):
        # NB: This assumes that the MMR and CUUID are kept up to date
        #     and that those that are read don't change on their own

        if attr_path != '':
            raise DE1APIAttributeError(
                "MMR reads do not support attr_path "
                f"{isat}")

        # For now, assume everything is kept current

        # TODO: Unify with replication in PATCH operation

        try:
            retval = de1._mmr_dict[target].data_decoded
        except KeyError:
            retval = None
        if retval is None:
            t0 = time.time()
            ready = await de1.read_one_mmr0x80(target)
            await ready.wait()
            retval = de1._mmr_dict[target].data_decoded
            t1 = time.time()
            logger.debug(
                f"Read of {target.__repr__()} took \t"
                f"{(t1 - t0) * 1000:6.1f} ms"
            )

    elif inspect.isclass(target) and issubclass(target, PackedAttr):
        # NB: This assumes that the MMR and CUUID are kept up to date
        #     and that those that are read don't change on their own
        try:
            obj = (de1._cuuid_dict[target.cuuid]).last_value
        except KeyError:
            logger.info(
                f"No last value for {target.cuuid}"
            )
            obj = None
        if obj is None:
            t0 = time.time()
            obj = await de1.read_cuuid(target.cuuid)
            t1 = time.time()
            logger.debug(
                f"Read of {target} took \t{(t1 - t0) * 1000:6.1f} ms"
            )
        retval = rgetattr(obj, attr_path)

    else:
        raise DE1APITypeError(
            f"Mapping target of {target} is not recognized"
        )

    return fix_enums(retval)


async def _get_mapping_to_dict(partial_dict: dict,
                               flow_sequencer: FlowSequencer) -> dict:
    """
    Takes a "branch" of a mapping and
      * Fills in any IsAt values
      * Recursively calls itself if a dict
      * Passes any other values unmodified
    """
    if not isinstance(partial_dict, dict):
        raise DE1APITypeError(f"Expected a dict, not {type(partial_dict)}")

    retval = {}

    for k, v in partial_dict.items():
        if isinstance(v, IsAt):
            try:
                this_val = await _get_isat_value(v, flow_sequencer)
            except AttributeError:
                if PRUNE_EMPTY_NODES:
                    continue # Don't write the key's entry
                else:
                    this_val = math.nan
        elif isinstance(v, dict):
            this_val = await _get_mapping_to_dict(v, flow_sequencer)
            # Suppress aggregates with nothing to aggregate
            if len(this_val) == 0 and PRUNE_EMPTY_NODES:
                continue
        else:
            this_val = v
        retval[k] = this_val

    return retval

# TODO: set and get versions

def _get_target_sets_inner(partial_dict: dict,
                           dict_of_sets: dict[
                               str, set[Union[PackedAttr, MMR0x80LowAddr]]],
                           include_can_read: bool,
                           include_can_write: bool):
    """
    Takes a "branch" of a mapping and returns a dict with two keys,
    'PacketAttr' and 'MMR0x80LowAddr', each with a set of targets.
    The dict_of_sets is modified in-place.
    """
    if not isinstance(partial_dict, dict):
        raise DE1APITypeError(f"Expected a dict, not {type(partial_dict)}")

    for k, isat in partial_dict.items():

        if isinstance(isat, IsAt):
            target = isat.target
            if not ((inspect.isclass(target) and issubclass(target, PackedAttr))
                    or isinstance(target, MMR0x80LowAddr)):
                continue
            writable = target.can_write \
                       and not (isat.read_only
                                or (isat.attr_path is None
                                    and isat.setter_path is None))
            readable = target.can_read and isat.attr_path is not None
            if ((include_can_read and readable)
                    or (include_can_write and writable)):
                if isinstance(target, MMR0x80LowAddr):
                    dict_of_sets['MMR0x80LowAddr'].add(target)
                elif inspect.isclass(target) and issubclass(target, PackedAttr):
                    dict_of_sets['PackedAttr'].add(target)
            else:
                if not readable and not writable:
                    logger.error(
                        "IsAt should have either or both attr_path or setter_path "
                        f"not None: {isat.__repr__()}"
                    )


        elif isinstance(isat, dict):
            _get_target_sets_inner(isat, dict_of_sets,
                                   include_can_read, include_can_write)


def get_target_sets(mapping: dict,
                    include_can_read=False, include_can_write=False) \
        -> dict[str, set[Union[MMR0x80LowAddr, PackedAttr]]]:

    retval = {
        'MMR0x80LowAddr': set(),
        'PackedAttr': set()
    }

    _get_target_sets_inner(mapping, retval,
                           include_can_read, include_can_write)
    return retval


async def get_resource_to_dict(resource: Resource,
                               flow_sequencer: FlowSequencer) -> dict:

    mapping = MAPPING[resource]
    de1 = flow_sequencer.de1

    # target_sets = get_target_sets(mapping)
    # pa_coros = list(map(lambda pa: de1.read_cuuid(pa.cuuid),
    #                     (target_sets['PackedAttr'])))
    # mmr_coros = list(map(lambda mmr: de1.read_one_mmr0x80(mmr),
    #                     (target_sets['MMR0x80LowAddr'])))
    # t0 = time.time()
    # # result = await asyncio.gather(*pa_coros) # 390-490 ms for 4
    # for coro in pa_coros:  # This takes 390 ms
    #     await coro
    # t1 = time.time()
    # logger.debug(
    #     f"Read of pa_coros took \t{(t1 - t0) * 1000:6.1f} ms"
    # )
    # t0 = time.time()
    # result = await asyncio.gather(*mmr_coros)  # Needs lock
    # await de1.read_standard_mmr_registers()  # This takes 1.2 seconds
    #                                          # and needs check for ready
    # t1 = time.time()
    # logger.debug(
    #     f"Read of mmr_coros took \t{(t1 - t0) * 1000:6.1f} ms"
    # )
    return await _get_mapping_to_dict(mapping, flow_sequencer)


# PATCH and PUT are related, but have slightly different requirements
#
# For PATCH, it is sufficient that each entry from the request has
# a corresponding entry in the overall mapping dictionary
#
# For PUT it is required that each element in the mappig dictionary
# have a corresponding entry in the request dictionary (completeness)
#
# TODO: How to handle read-only attributes in the PUT case is TBD

async def patch_resource_from_dict(resource: Resource, values_dict: dict,
                                   flow_sequencer: FlowSequencer):

    mapping = MAPPING[resource]

    # Get the list of PackedAttrs that need to be patched (properties and
    # MMRs are handled one at a time, as they are atomic), lock from changes,
    # get copies of current PackedAttrs to patch

    # TODO: Managing locks
    # TODO: PackedAttr "getter" that will wait on a pending update, if one is
    #       in flight, as well as unify the retrieval if not present

    target_sets = get_target_sets(values_dict, include_can_write=True)

    # Lock here
    de1 = flow_sequencer.de1

    for pa in target_sets['PackedAttr']:
        pa: PackedAttr
        cuuid = pa.cuuid
        try:
            last_value = de1._cuuid_dict[cuuid]._last_value
        except KeyError:
            last_value = None
        if last_value is None:
            t0 = time.time()
            last_value = await de1.read_cuuid(cuuid)
            t1 = time.time()
            logger.debug(
                f"Read of {cuuid} took \t"
                f"{(t1 - t0) * 1000:6.1f} ms"
            )

        # Don't load them all, just make sure they are there
        # Only load if they are being changed
        # pending_packed_attrs[pa] = last_value

    pending_packed_attrs = {}
    await _patch_dict_to_mapping_inner(values_dict,
                                       mapping,
                                       pending_packed_attrs,
                                       flow_sequencer)

    # if there are pending_packed_attrs, send them

    # Potentially gather, but may not be faster
    for pa in pending_packed_attrs.values():
        await de1.write_packed_attr(pa)

    # release locks


    return


async def _patch_dict_to_mapping_inner(partial_value_dict: dict,
                                       partial_mapping_dict: dict,
                                       pending_packed_attrs: dict[
                                           type(PackedAttr), PackedAttr],
                                       flow_sequencer: FlowSequencer):
    """
    This assumes that everything has been determined as "valid"
    """

    # TODO: PATCH Method for HTTP specifies that PATCH is to be atomic
    #       This isn't completely possible as there is no
    #       roll-back capability implemented at this time.
    #       To at least be somewhat compliant, all keys
    #       should be processed as fully as possible
    #       prior to writing any to their targets.
    #
    #       https://datatracker.ietf.org/doc/html/rfc5789
    #
    #       NB: Although this is similar to JSON Merge Patch
    #       https://datatracker.ietf.org/doc/html/rfc7386
    #       it is subtly different in that a JSON 'null'
    #       is interpreted as the valid, Python 'None'
    #       rather than as a request to delete an element:
    #
    #           This design means that merge patch documents are suitable for
    #           describing modifications to JSON documents that primarily
    #           use objects for their structure and do not make use of
    #           explicit null values.
    #
    #           The merge patch format is not appropriate for all JSON syntaxes.

    for key, new_value in partial_value_dict.items():

        try:
            mapping_isat = partial_mapping_dict[key]
        except KeyError:
            raise DE1APIKeyError(
                f"Unable to find mapping for {key} on the specified path"
            )

        if isinstance(mapping_isat, IsAt):
            target = mapping_isat.target
            attr_path = mapping_isat.attr_path
            setter_path = mapping_isat.setter_path

            if mapping_isat.read_only or attr_path is None and setter_path is None:
                raise DE1APIValueError(
                    f"Mapping for '{key}': {mapping_isat} is not writable"
                )

            if target in (DE1, FlowSequencer, Scale):
                if target is DE1:
                    this_target = flow_sequencer.de1
                elif target is FlowSequencer:
                    this_target = flow_sequencer
                elif target is Scale:
                    this_target = flow_sequencer.scale_processor.scale
                else:
                    raise DE1APITypeError(
                        f"Unsupported target for '{key}': {mapping_isat}")

                if setter_path is not None:
                    setter = rgetattr(this_target, setter_path)
                    await _value_to_property_setter(setter, new_value)
                else:
                    rsetattr(this_target, attr_path, new_value)

            elif isinstance(target, MMR0x80LowAddr):

                # MMR writes need to be serial and are atomic in that
                # each writable MMR is a single value.
                # As a result, just write it here and now.

                if attr_path != '':
                    raise DE1APIValueError(
                        "MMR writes do not support attr_path "
                        f"{target} {mapping_isat}")

                if setter_path is not None:
                    raise DE1APIValueError(
                        "MMR writes do not support setter_path "
                        f"{target} {mapping_isat}")

                mmr_write = pack_one_mmr0x80_write(
                    addr_low= target,
                    value= new_value,
                )

                logger.debug(f"MMR to be written: {mmr_write.as_wire_bytes()}")

                de1 = flow_sequencer.de1
                await de1.write_packed_attr(mmr_write)

                # TODO: Should this wait on ready.wait() ??
                #       Or is there a way to collect them all for later?
                ns: NotificationState = de1._mmr_dict[target]
                await ns.ready_event.wait()

            elif inspect.isclass(target) and issubclass(target, PackedAttr):
                # NB: This assumes that the CUUIDs are kept up to date
                #     and that those that are read don't change on their own

                de1 = flow_sequencer.de1
                packed_attr = (de1._cuuid_dict[target.cuuid]).last_value
                # TODO: Is this the right way to deal with these?
                if packed_attr is None:
                    packed_attr = await de1.read_cuuid(target.cuuid)
                old_value = rgetattr(packed_attr, attr_path)
                if new_value != old_value:
                    if not target in pending_packed_attrs:
                        pending_packed_attrs[target] = copy.deepcopy(packed_attr)
                    rsetattr(pending_packed_attrs[target], attr_path, new_value)

                # Send in outer method once all nodes are visited

            else:
                raise DE1APITypeError(
                    f"Mapping target of {target} is not recognized")

        elif isinstance(mapping_isat, dict):
            this_val = await _patch_dict_to_mapping_inner(
                partial_value_dict[key],
                partial_mapping_dict[key],
                pending_packed_attrs,
                flow_sequencer)
        else:
            this_val = new_value
