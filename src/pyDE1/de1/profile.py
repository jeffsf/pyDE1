"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

from __future__ import annotations

import enum
import hashlib
import json
from copy import deepcopy
from typing import Union, Optional, List

import pyDE1
from pyDE1.de1.c_api import (
    ShotDescHeader, ShotFrame, ShotExtFrame, ShotTail, FrameFlags, HeaderWrite,
    FrameWrite_ShotFrame, FrameWrite_ShotExtFrame, FrameWrite_ShotTail
)

logger = pyDE1.getLogger('DE1.Profile')


class DE1ProfileValidationError (ValueError):
    def __init__(self, *args, **kwargs):
        super(DE1ProfileValidationError, self).__init__(args, kwargs)


class DE1ProfileValidationErrorJSON (DE1ProfileValidationError):
    def __init__(self, *args, **kwargs):
        super(DE1ProfileValidationErrorJSON, self).__init__(args, kwargs)


class SourceFormat (enum.Enum):
    JSONv2 = 'JSONv2'


class Profile:
    """
    Represents an internal form of a profile than can be loaded to the DE1

    This is subclassed immediately to be able to accommodate FROTH-based profiles
    """

    def __init__(self):
        self._id: Optional[str] = None
        self._source: Optional[Union[str, bytes, bytearray]] = None
        self._source_format: Optional[str] = None
        self._fingerprint: Optional[str] = None
        self.title: Optional[str] = None
        self.author: Optional[str] = None
        self.notes: Optional[str] = None
        self.beverage_type: Optional[str] = None
        self.move_on_weight_list: Optional[list[Optional[Union[float,int]]]] = None

    @property
    def id(self) -> Optional[str]:
        """
        Unique ID of the "source" (byte stream) of the profile.
        If no source, then the fingerprint

        May be None if the profile hasn't been sent to the DE1
        """
        return self._id

    @property
    def fingerprint(self) -> Optional[str]:
        """
        The fingerprint (UUID) of the "program" sent to the DE1

        May be None if the profile hasn't been sent to the DE1
        """
        return self._fingerprint

    @property
    def source(self) -> Optional[Union[str, bytes, bytearray]]:
        """
        The "source file" contents, usable for reconstruction, if any
        """
        return self._source

    @source.setter
    def source(self, value):
        self._source = value
        self._id = hashlib.sha1(value).hexdigest()

    @property
    def source_format(self) -> Optional[SourceFormat]:
        """
        Format of "source file", if any
        """
        return self._source_format

    def from_json(self, json_str_or_bytes: Union[str,
                                                 bytes,
                                                 bytearray]) -> Profile:
        """
        Should set self._source_format = SourceFormat.JSONv2
        """
        raise NotImplementedError

    def as_json(self) -> dict:
        raise NotImplementedError

    def validate(self) -> bool:
        raise NotImplementedError

    def regenerate_source(self):
        """
        MUST be called whenever changes are made to the underlying components
        to ensure that the id, source, source_type, and fingerprint are correct
        """
        raise NotImplementedError


class ProfileByFrames (Profile):

    _MAX_SHOT_FRAMES = 20
    _EXT_OFFSET = 32

    def __init__(self):
        super(ProfileByFrames, self).__init__()
        self._ShotDescHeader: Optional[ShotDescHeader] = None
        self._shot_frames: List[ShotFrame] = []
        self._shot_ext_frames: List[Optional [ShotExtFrame]] = []
        self._ShotTail: Optional[ShotTail] = None

        # These come from v2 profiles
        self.tank_temperature: Optional[float] = None
        self.target_weight: Optional[float] = None
        self.target_volume: Optional[float] = None
        self.number_of_preinfuse_frames: Optional[float] = None

    def header_write(self):
        return HeaderWrite(deepcopy(self._ShotDescHeader))

    def shot_frame_writes(self):
        return [
            FrameWrite_ShotFrame(n, f) for n, f
            in zip(range(0, len(self._shot_frames)),
                   deepcopy(self._shot_frames))
        ]

    def ext_shot_frame_writes(self):
        """
        May include None as elements of .Frame
        """
        unfiltered = [
            FrameWrite_ShotExtFrame(n + self._EXT_OFFSET, f) for n, f
            in zip(range(0, len(self._shot_frames)),
                   deepcopy(self._shot_ext_frames))
        ]
        return filter(lambda fw : fw.Frame is not None, unfiltered)

    def shot_tail_write(self):
        return FrameWrite_ShotTail(len(self._shot_frames), self._ShotTail)

    def validate(self) -> bool:
        if None in [
            self._ShotDescHeader,
            self._shot_frames,
            # self._shot_ext_frames,
            self._ShotTail,
        ]:
            raise DE1ProfileValidationError("One or more required values are None")
        if isinstance(self._shot_frames, list):
            for f in self._shot_frames:
                if not isinstance(f, ShotFrame):
                    raise DE1ProfileValidationError("ShotFrame list contains something else")
        else:
            raise DE1ProfileValidationError("ShotFrame list isn't a list")
        if isinstance(self._shot_ext_frames, list):
            for f in self._shot_ext_frames:
                if not isinstance(f, (ShotExtFrame, type(None))):
                    raise DE1ProfileValidationError("ShotExtFrame list contains something else")
        else:
            raise DE1ProfileValidationError("ShotExtFrame list isn't a list")
        if not isinstance(self._ShotTail, ShotTail):
            raise DE1ProfileValidationError("ShotTail isn't a ShotTail")
        if len(self._shot_frames) != self._ShotDescHeader.NumberOfFrames:
            raise DE1ProfileValidationError(
                "Inconsistent number of frames "
                f"({len(self._shot_frames)}) "
                f"with header ({self._ShotDescHeader.NumberOfFrames})"
            )
        if len(self._shot_ext_frames)  > len(self._shot_ext_frames):
            raise DE1ProfileValidationError(
                f"More ShotExtFrames ({len(self._shot_ext_frames)}) than "
                f"ShotFrames ({len(self._shot_frames)})"
            )
        if len(self._shot_frames) > self._MAX_SHOT_FRAMES:
            raise DE1ProfileValidationError(
                f"Too many ShotFrames ({len(self._shot_frames)})"
            )

        # TODO: The PackedAttr classes should self-validate as well
        return True

    def from_json(self, json_str_or_bytes: Union[str,
                                                 bytes,
                                                 bytearray]) -> ProfileByFrames:
        """
        Rounding of the supplied values has been removed so that
        the "source" preserved and used for the "fingerprint"
        is the same as the input.
        """

        self.source = json_str_or_bytes     # This sets the id as well
                                            # Fingerprint is set on upload
        self.move_on_weight_list = []

        try:
            json_dict = json.loads(json_str_or_bytes)
        except json.decoder.JSONDecodeError as e:
            if isinstance(e.doc, (bytes, bytearray, str)):
                point_right = "\u27a7"
                pos = e.pos
                error_context = "{}{}{}{}".format(
                    e.doc[pos-10:pos],
                    point_right,
                    e.doc[pos],
                    e.doc[pos+1:pos+10],
                )
                e.args = (f"{', '.join(e.args)}: {error_context}",)
            raise e


        try:
            # Permit simple semantic versioning
            v = str(json_dict['version'])
            vs = v.split('.')
            if vs[0] != "2":
                raise DE1ProfileValidationErrorJSON(
                    f"Only version 2 profiles are recognized, not '{v}'")
        except KeyError:
            raise DE1ProfileValidationErrorJSON(
                f"Only version 2 profiles are recognized, no version found")

        self._source_format = SourceFormat.JSONv2

        # ShotDescHeader
        _header_v = 1
        _minimum_pressure_default = 0
        _maximum_flow_default = 10   # TODO: Reconfirm that this is sufficient

        # ShotFrame
        _ignore_limit_default = True

        # ShotTail
        _ignore_pi_default = True

        self._ShotDescHeader = ShotDescHeader(
            HeaderV=_header_v,
            NumberOfFrames=None,
            NumberOfPreinfuseFrames=int(round(float(
                json_dict['target_volume_count_start']))),
            MinimumPressure=_minimum_pressure_default,
            MaximumFlow=_maximum_flow_default,
        )

        for step in json_dict['steps']:

            flag = 0x00
            pump = step['pump']
            sensor = step['sensor']
            transition = step['transition']
            # ignore_limit = None

            temperature = float(step['temperature'])
            seconds = float(step['seconds'])
            volume = float(step['volume'])
            if 'weight' in step:
                self.move_on_weight_list.append(float(step['weight']))
            else:
                self.move_on_weight_list.append(None)

            if pump == 'flow':
                flag |= FrameFlags.CtrlF
            elif pump == 'pressure':
                flag |= FrameFlags.CtrlP
            else:
                raise DE1ProfileValidationErrorJSON(
                    f"Unrecognized pump: {pump}")

            # TODO: Confirm DoCompare functionality in DE1 firmware for docs
            if 'exit' in step:
                flag |= FrameFlags.DoCompare

                exit_condition = step['exit']['condition']
                exit_type = step['exit']['type']

                if exit_condition == 'over':
                    flag |= FrameFlags.DC_GT
                elif exit_condition == 'under':
                    flag |= FrameFlags.DC_LT
                else:
                    raise DE1ProfileValidationErrorJSON(
                        f"Unrecognized exit condition: {exit_condition}")

                if exit_type == 'flow':
                    flag |= FrameFlags.DC_CompF
                elif exit_type == 'pressure':
                    flag |= FrameFlags.DC_CompP
                else:
                    raise DE1ProfileValidationErrorJSON(
                        f"Unrecognized exit type: {exit_type}")

            else:
                flag |= FrameFlags.DontCompare

            if sensor == 'water':
                flag |= FrameFlags.TMixTemp
            elif sensor == 'coffee':
                flag |= FrameFlags.TBasketTemp
            else:
                raise DE1ProfileValidationErrorJSON(
                    f"Unrecognized sensor: {sensor}")

            if transition == 'smooth':
                flag |= FrameFlags.Interpolate
            elif transition == 'fast':
                flag |= FrameFlags.DontInterpolate
            else:
                raise DE1ProfileValidationErrorJSON(
                    f"Unrecognized transition: {transition}")

            if _ignore_limit_default:
                flag |= FrameFlags.IgnoreLimit
            else:
                flag |= FrameFlags.ObserveLimit

            # if flag & FrameFlags.CtrlP:  # Fails as .CtrlP is the "0" bit
            if pump == 'pressure':
                SetVal = float(step['pressure'])
            else:
                SetVal = float(step['flow'])

            if flag & FrameFlags.DoCompare:
                TriggerVal = float(step['exit']['value'])
            else:
                TriggerVal = 0

            self._shot_frames.append(ShotFrame(
                Flag=flag,
                SetVal=SetVal,
                Temp=temperature,
                FrameLen=seconds,
                TriggerVal=TriggerVal,
                MaxVol=volume
            ))

            if ('limiter' in step
                    and round(float(step['limiter']['value']), 2) > 0):

                value = float(step['limiter']['value'])
                range = float(step['limiter']['range'])

                self._shot_ext_frames.append(ShotExtFrame(
                    MaxFlowOrPressure=value,
                    MaxForPRange=range
                ))

            else:
                # "Write Extension frames (write all N extension frames,
                # OR just relevant frames. Doesn't matter)"
                self._shot_ext_frames.append(None)

        self._ShotDescHeader.NumberOfFrames = len(self._shot_frames)

        self._ShotTail = ShotTail(
            MaxTotalVolume=int(round(float((
                json_dict['target_volume'])))),
            ignore_pi=_ignore_pi_default,
        )

        if 'tank_temperature' in json_dict:
            self.tank_temperature = float(json_dict['tank_temperature'])

        if 'target_weight' in json_dict:
            self.target_weight = float(json_dict['target_weight'])

        if 'target_volume' in json_dict:
            self.target_volume = float(json_dict['target_volume'])

        if 'target_volume_count_start' in json_dict:
            self.number_of_preinfuse_frames = \
                int(round(float(json_dict['target_volume_count_start'])))

        try:
            self.title = json_dict['title']
        except KeyError:
            pass

        try:
            self.author = json_dict['author']
        except KeyError:
            pass

        try:
            self.notes = json_dict['notes']
        except KeyError:
            pass

        try:
            self.beverage_type = json_dict['beverage_type']
        except KeyError:
            pass

        while (len(self.move_on_weight_list)
               and self.move_on_weight_list[-1] is None):
            self.move_on_weight_list.pop()

        return self


if __name__ == '__main__':
    profile = ProfileByFrames()
    profile.from_json_file('jmk_eb5.json')
    h = profile.header_write()
    f = profile.shot_frame_writes()
    for sf in f:
        print(sf.as_wire_bytes().hex(" "), sf.log_string(), sep=" ")
    e = profile.ext_shot_frame_writes()
    t = profile.shot_tail_write()
    debug = True
    print(debug)
    ref = [
        "47 50 bb 94 40 04 64",
        "43 00 9f 8f 18 04 64",
        "60 90 b8 32 00 04 64",
        "40 90 b8 14 00 04 64",
        "60 40 b8 99 00 04 64"
        ]
    for rf in ref:
        ref_sf = ShotFrame().from_wire_bytes(bytes.fromhex(rf))
        print(" ", rf, ref_sf.log_string(), sep="  ")


