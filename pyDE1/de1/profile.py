"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

from __future__ import annotations

import asyncio
import enum
import io
import json

from copy import deepcopy
from typing import Any, Union, Optional, List

from pyDE1.de1.c_api import ShotDescHeader, ShotFrame, ShotExtFrame, ShotTail, \
    FrameFlags, ShotSettings, SteamSetting, HeaderWrite, \
    FrameWrite_ShotFrame, FrameWrite_ShotExtFrame, FrameWrite_ShotTail



class DE1ProfileValidationError (ValueError):
    def __init__(self, *args, **kwargs):
        super(DE1ProfileValidationError, self).__init__(args, kwargs)


class DE1ProfileValidationErrorJSON (DE1ProfileValidationError):
    def __init__(self, *args, **kwargs):
        super(DE1ProfileValidationErrorJSON, self).__init__(args, kwargs)


class Profile:
    """
    Represents an internal form of a profile than can be loaded to the DE1

    This is subclassed immediately to be able to accommodate FROTH-based profiles
    """

    def __init__(self):
        pass

    def from_json(self, json_representation: dict) -> Profile:
        raise NotImplementedError

    def from_json_file(self, file: Union[str, io.TextIOBase, io.BufferedIOBase]) -> Profile:
        if isinstance(file, str):
            with open(file, 'r') as profile_fh:
                profile_json = json.load(profile_fh)
        else:
            profile_json = json.load(file)
        self.from_json(profile_json)
        return self

    def as_json(self) -> dict:
        raise NotImplementedError

    def validate(self) -> bool:
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

    def from_json(self, json_as_dict: dict,
                  round_to_two_decimals=True) -> ProfileByFrames:
        """
        Somewhere in the prior translation process to JSON, "off by one bit"
        caused "pressure": "8.999999999999993"

        By default, round floats to two decimal digits
        """

        try:
            if (v := int(json_as_dict['version'])) != 2:
                raise DE1ProfileValidationErrorJSON(
                    f"Only version 2 profiles are recognized, not '{v}'")
        except KeyError:
            raise DE1ProfileValidationErrorJSON(
                f"Only version 2 profiles are recognized, no version found")

        # TODO: Confirm or determine:

        # ShotDescHeader
        _header_v = 1
        _minimum_pressure_default = 0
        _maximum_flow_default = 10   # What is the internal limit?

        # ShotFrame
        _ignore_limit_default = True

        # ShotTail
        _ignore_pi_default = True

        # TODO: Decide how to handle non-DE1 parameters:
        #       beverage_type
        #       target_weight
        #       target_volume
        #       metadata; title, author, notes, hidden, reference file, ...

        self._ShotDescHeader = ShotDescHeader(
            HeaderV=_header_v,
            NumberOfFrames=None,
            NumberOfPreinfuseFrames=int(round(float(
                json_as_dict['target_volume_count_start']))),
            MinimumPressure=_minimum_pressure_default,
            MaximumFlow=_maximum_flow_default,
        )

        for step in json_as_dict['steps']:

            flag = 0x00
            pump = step['pump']
            sensor = step['sensor']
            transition = step['transition']
            # ignore_limit = None

            temperature = float(step['temperature'])
            seconds = float(step['seconds'])
            volume = float(step['volume'])

            if pump == 'flow':
                flag |= FrameFlags.CtrlF
            elif pump == 'pressure':
                flag |= FrameFlags.CtrlP
            else:
                raise DE1ProfileValidationErrorJSON(
                    f"Unrecognized pump: {pump}")

            # TODO: Confirm DoCompare
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
                flag |= FrameFlags.DontIgnoreLimit

            # if flag & FrameFlags.CtrlP:  # Fails as .CtrlP is the "0" bit
            if pump == 'pressure':
                SetVal = float(step['pressure'])
            else:
                SetVal = float(step['flow'])

            if flag & FrameFlags.DoCompare:
                TriggerVal = float(step['exit']['value'])
            else:
                TriggerVal = 0

            if round_to_two_decimals:
                SetVal = round(SetVal, 2)
                TriggerVal = round(TriggerVal, 2)
                temperature = round(temperature, 2)
                seconds = round(seconds, 2)
                volume = round(volume, 2)

            self._shot_frames.append(ShotFrame(
                Flag=flag,
                SetVal=SetVal,
                Temp=temperature,
                FrameLen=seconds,
                TriggerVal=TriggerVal,
                MaxVol=volume
            ))

            # Is a ShotExtFrame needed for this frame?

            if ('limiter' in step
                    and round(float(step['limiter']['value']), 2) > 0):

                value = float(step['limiter']['value'])
                range = float(step['limiter']['range'])

                if round_to_two_decimals:
                    value = round(value, 2)
                    range = round(range, 2)

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
                json_as_dict['target_volume'])))),
            ignore_pi=_ignore_pi_default,
        )

        if 'tank_temperature' in json_as_dict:
            self.tank_temperature = float(json_as_dict['tank_temperature'])

        if 'target_weight' in json_as_dict:
            self.target_weight = float(json_as_dict['target_weight'])

        if 'target_volume' in json_as_dict:
            self.target_volume = float(json_as_dict['target_volume'])

        if 'target_volume_count_start' in json_as_dict:
            self.number_of_preinfuse_frames = \
                int(round(float(json_as_dict['target_volume_count_start'])))

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


