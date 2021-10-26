"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import copy
import inspect
import math  # for nan to be uniquely math.nan
import time
from functools import reduce
from typing import Union, Dict, Set

import pyDE1.scanner
from pyDE1.config import config
from pyDE1.de1 import DE1
from pyDE1.de1.c_api import PackedAttr, MMR0x80LowAddr, pack_one_mmr0x80_write
from pyDE1.de1.notifications import MMR0x80Data
from pyDE1.dispatcher.mapping import MAPPING, TO, IsAt
from pyDE1.dispatcher.resource import Resource
from pyDE1.exceptions import (
    DE1APITypeError, DE1APIValueError, DE1APIAttributeError, DE1APIKeyError,
    DE1NotConnectedError
)
from pyDE1.flow_sequencer import FlowSequencer
from pyDE1.scale.processor import ScaleProcessor
from pyDE1.scanner import DiscoveredDevices, scan_from_api
from pyDE1.utils import prep_for_json
from pyDE1.utils_public import rgetattr, rsetattr

logger = pyDE1.getLogger('Inbound.Implementation')

"""
How this works:

http/run.py creates an APIRequest and adds it to the queue

The _request_queue_processor from dispatcher picks it up and calls
GET:        resource_dict = await get_resource_to_dict(got.resource)
PATCH, PUT: await patch_resource_from_dict(got.resource, got.payload)

The resource_dict becomes a payload for the APIResponse object that is queued

To be able to return meaningful results from PUT/PATCH, the recipient 
needs to know which of possibly many elements the result comes from.
As most won't be returning anything, at least right now, append each,
within a nested dict, to a list and pass that back.
"""


def get_timeout(prop, value):
    bound_class = prop.__self__.__class__
    name = prop.__name__
    timeout = config.http.ASYNC_TIMEOUT
    if name == 'connectivity_setter' and value:
        timeout = config.bluetooth.CONNECT_TIMEOUT + 0.100
    elif name in ('change_de1_to_id', 'change_scale_to_id'):
        if value is None:
            timeout = config.bluetooth.DISCONNECT_TIMEOUT
        else:
            timeout = config.bluetooth.CONNECT_TIMEOUT \
                      + config.http.ASYNC_TIMEOUT + 0.100
    elif name == 'first_if_found':
        timeout = config.bluetooth.SCAN_TIME \
                  + config.bluetooth.CONNECT_TIMEOUT \
                  + config.http.ASYNC_TIMEOUT + 0.100
    elif name == 'upload_json_v2_profile':
        timeout = config.http.PROFILE_TIMEOUT
    elif name == 'stop_at_time_set_async':
        timeout = config.http.ASYNC_TIMEOUT * 2

    elif name == 'upload_firmware_from_content':
        timeout = config.http.FIRMWARE_TIMEOUT

    if DE1().uploading_firmware:
        timeout += config.de1.CUUID_LOCK_WAIT_TIMEOUT

    return timeout


async def _prop_value_setter(prop, value):

    if inspect.isroutine(prop):
        if inspect.iscoroutinefunction(prop):
            retval = await asyncio.wait_for(prop(value),
                                            get_timeout(prop, value))
        else:
            retval = prop(value)
    else:
        raise DE1APITypeError (f"Setter {prop} is not callable")

    return retval


async def _prop_value_getter(prop):

    if inspect.isroutine(prop):
        if inspect.iscoroutinefunction(prop):
            retval = await asyncio.wait_for(prop(),
                                            get_timeout(prop, None))
        else:
            retval = prop()
    else:
        raise DE1APITypeError (f"Setter {prop} is not callable")

    return retval


# NB: This assumes that the MMR and CUUID are kept up to date
#     and that those that are read don't change on their own

async def _get_isat_value(isat: IsAt):

    # TODO: if IsAt.use_getter is implemented in the future, change here

    target = isat.target
    attr_path = isat.attr_path
    if attr_path is None:
        raise DE1APIAttributeError(f"Write-only attribute {isat.__repr__()}")

    de1 = DE1()
    flow_sequencer = FlowSequencer()
    scale_processor = ScaleProcessor()
    scale = scale_processor.scale
    dd = DiscoveredDevices()

    retval = None

    # For any attribute or property with a getter, getattr() "just works"
    # If possibly a callable, need to
    #     await _prop_value_getter(rgetattr(target, attr_path))

    if target == TO.DE1:
        retval = rgetattr(de1, attr_path)

    elif target == TO.FlowSequencer:
        retval = rgetattr(flow_sequencer, attr_path)

    elif target == TO.Scale:
        retval = rgetattr(scale, attr_path)

    elif target == TO.ScaleProcessor:
        retval = rgetattr(scale_processor, attr_path)

    elif target == TO.DiscoveredDevices:
        # Need to wrap as devices_for_json is async
        retval = await _prop_value_getter(rgetattr(dd, attr_path))

    elif isinstance(target, MMR0x80LowAddr):
        # NB: This assumes that the MMR and CUUID are kept up to date
        #     and that those that are read don't change on their own

        if not de1.is_ready:
            raise DE1NotConnectedError(
                "DE1 is not connected at last-chance check")

        if attr_path != '':
            raise DE1APIAttributeError(
                "MMR reads do not support attr_path "
                f"{isat}")

        # For now, assume everything is kept current

        # TODO: Unify with replication in PATCH operation

        if target.value > de1.feature_flag.last_mmr0x80:
            retval = None
            logger.info(
                f"Skipping (not in FW) {target.name}, "
                f"0x{target.value:04x} > 0x{de1.feature_flag.last_mmr0x80:04x}")
        else:
            try:
                retval = de1._mmr_dict[target].data_decoded
            except KeyError:
                retval = None
            if retval is None:
                t0 = time.time()
                # TODO: Can this be simplified/clarified?
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

        if not de1.is_ready:
            raise DE1NotConnectedError(
                "DE1 is not connected at last-chance check")

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

    return prep_for_json(retval)


async def _get_mapping_to_dict(partial_dict: dict) -> dict:
    """
    Takes a "branch" of a mapping and
      * Fills in any IsAt values
      * Recursively calls itself if a dict
      * Passes any other values unmodified
    """

    if isinstance(partial_dict, IsAt):
        partial_dict = { None: partial_dict }

    if not isinstance(partial_dict, dict):
        raise DE1APITypeError(f"Expected a dict, not {type(partial_dict)}")

    retval = {}

    for k, v in partial_dict.items():
        if isinstance(v, IsAt):
            try:
                this_val = await _get_isat_value(v)
            except AttributeError:
                if config.http.PRUNE_EMPTY_NODES:
                    continue # Don't write the key's entry
                else:
                    this_val = math.nan
        elif isinstance(v, dict):
            this_val = await _get_mapping_to_dict(v)
            # Suppress aggregates with nothing to aggregate
            if len(this_val) == 0 and config.http.PRUNE_EMPTY_NODES:
                continue
        else:
            this_val = v
        retval[k] = this_val

    return retval

# TODO: set and get versions (no recollection of what this means)

def _get_target_sets_inner(partial_dict: dict,
                           dict_of_sets: Dict[
                               str, Set[Union[PackedAttr, MMR0x80LowAddr]]],
                           include_can_read: bool,
                           include_can_write: bool):
    """
    Takes a "branch" of a mapping and returns a dict with two keys,
    'PacketAttr' and 'MMR0x80LowAddr', each with a set of targets.
    The dict_of_sets is modified in-place.
    """

    # See also validate.py
    # Valid: dict with dict
    #        IsAt with byte, bytearray (profile or firmware)
    if isinstance(partial_dict, IsAt):
        partial_dict = { None: partial_dict }

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
                        "IsAt should have either or both "
                        f"attr_path or setter_path not None: {isat.__repr__()}"
                    )

        elif isinstance(isat, dict):
            _get_target_sets_inner(isat, dict_of_sets,
                                   include_can_read, include_can_write)


def get_target_sets(mapping: dict,
                    include_can_read=False, include_can_write=False) \
        -> Dict[str, Set[Union[MMR0x80LowAddr, PackedAttr]]]:

    retval = {
        'MMR0x80LowAddr': set(),
        'PackedAttr': set()
    }

    _get_target_sets_inner(mapping, retval,
                           include_can_read, include_can_write)
    return retval


async def get_resource_to_dict(resource: Resource) -> dict:

    mapping = MAPPING[resource]
    return await _get_mapping_to_dict(mapping)


# PATCH and PUT are related, but have slightly different requirements
#
# For PATCH, it is sufficient that each entry from the request has
# a corresponding entry in the overall mapping dictionary
#
# For PUT it is required that each element in the mappig dictionary
# have a corresponding entry in the request dictionary (completeness)
#

# TODO: How to handle read-only attributes in the PUT case is TBD

async def patch_resource_from_dict(resource: Resource, values_dict: dict):

    mapping = MAPPING[resource]

    # Get the list of PackedAttrs that need to be patched (properties and
    # MMRs are handled one at a time, as they are atomic), lock from changes,
    # get copies of current PackedAttrs to patch

    # TODO: Managing locks
    # TODO: PackedAttr "getter" that will wait on a pending update, if one is
    #       in flight, as well as unify the retrieval if not present

    # target_sets = get_target_sets(values_dict, include_can_write=True)

    # TODO: Optimize this -- this needs a mapping, the way it is written now
    #       It really should only retrieve those that are being changed
    #       in the case of a PATCH

    target_sets = get_target_sets(mapping, include_can_write=True)

    # Lock here
    de1 = DE1()
    flow_sequencer = FlowSequencer()

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

    # Valid: dict with dict
    #        IsAt with byte, bytearray (profile or firmware)
    if isinstance(mapping, dict) \
            and isinstance(values_dict, dict):
        pass
    elif isinstance(mapping, IsAt) \
        and isinstance(values_dict, (bytes, bytearray)):
        # coerce into "standard form"
        mapping = { None: mapping }
        values_dict = { None: values_dict }
    else:
        raise DE1APITypeError(
            "Mapping and patch inconsistent, "
            "dict with dict, IsAt with raw value "
            f"not {type(mapping)} with {type(values_dict)}"
        )

    results_list = list()
    await _patch_dict_to_mapping_inner(values_dict,
                                       mapping,
                                       pending_packed_attrs,
                                       list(),
                                       results_list)

    # if there are pending_packed_attrs, send them

    # Potentially gather, but may not be faster
    for pa in pending_packed_attrs.values():
        await de1.write_packed_attr(pa)

    # release locks

    return results_list


async def _patch_dict_to_mapping_inner(partial_value_dict: dict,
                                       partial_mapping_dict: dict,
                                       pending_packed_attrs: Dict[
                                           type(PackedAttr), PackedAttr],
                                       running_path: list,
                                       results_list: list):

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

    de1 = DE1()
    flow_sequencer = FlowSequencer()
    scale_processor = ScaleProcessor()
    scale = scale_processor.scale

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

            if isinstance(target, TO) and target != TO.DiscoveredDevices:
                if target == TO.DE1:
                    this_target = de1
                elif target == TO.FlowSequencer:
                    this_target = flow_sequencer
                elif target == TO.Scale:
                    this_target = scale
                elif target == TO.ScaleProcessor:
                    this_target = scale_processor
                else:
                    raise DE1APITypeError(
                        f"Unsupported target for '{key}': {mapping_isat}")

                if setter_path is not None:
                    # Allow for a non-property setter to return a value
                    setter = rgetattr(this_target, setter_path)
                    retval = await _prop_value_setter(setter, new_value)
                    if retval is not None:
                        # reduce(lambda a, b: {b: a}, [5,4,3,2,1], 'val')
                        #     {1: {2: {3: {4: {5: 'val'}}}}}
                        result_dict = reduce(lambda a, b: {b: a},
                                             running_path,
                                             retval)
                        results_list.append(result_dict)

                else:
                    rsetattr(this_target, attr_path, new_value)

            # TODO: Is there a better way to work with an unbound function?
            #       Maybe attach it to a module, rathern than a special case?
            elif target is None:
                if setter_path == 'scan_from_api':
                    retval = await scan_from_api(new_value)
                    if retval is not None:
                        # reduce(lambda a, b: {b: a}, [5,4,3,2,1], 'val')
                        #     {1: {2: {3: {4: {5: 'val'}}}}}
                        result_dict = reduce(lambda a, b: {b: a},
                                             running_path,
                                             retval)
                        results_list.append(result_dict)

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

                await de1.write_packed_attr(mmr_write)

                # TODO: Should this wait on ready.wait() ??
                #       Or is there a way to collect them all for later
                #       as a speed optimization?
                ns: MMR0x80Data = de1._mmr_dict[target]
                await ns.ready_event.wait()

            elif inspect.isclass(target) and issubclass(target, PackedAttr):
                # NB: This assumes that the CUUIDs are kept up to date
                #     and that those that are read don't change on their own

                packed_attr = (de1._cuuid_dict[target.cuuid]).last_value
                # TODO: Can this be sped up reliably?
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
            # TODO: Where did "this_val" (unused) come from?
            this_val = await _patch_dict_to_mapping_inner(
                partial_value_dict[key],
                partial_mapping_dict[key],
                pending_packed_attrs,
                # Prepend as reduce needs "reversed" list and need copy anyway
                running_path=[mapping_isat] + running_path,
                results_list=results_list)
        else:
            this_val = new_value
