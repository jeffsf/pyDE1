#!/usr/bin/env python3
"""
Copyright © 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Convert the de1app-written, Tcl-based profiles into JSON v2 format

Several fields that do not carry information, especially in the shot frames
are not present in this implementation.

Known limitations include:
  * No braces permitted in "text" fields (brace-quoted strings are OK)
"""

VERSION = {
    'app': '0.0.2',
    'format': '2.1',
}

import datetime
import os.path
import re
from pathlib import PurePath

import pyparsing
from pyparsing import (
    Suppress, Word,
    OneOrMore, ZeroOrMore,
    alphas, nums, alphanums, printables,
    common,
    dict_of,
    original_text_for,
)

from inspect import currentframe, getframeinfo
# Using PurePath here "normalizes" path
THIS_FILENAME = str(PurePath(getframeinfo(currentframe()).filename).name)
TIMESTAMP = datetime.datetime.now().astimezone().isoformat(timespec='seconds')

def pr_as_list(toks: pyparsing.results.ParseResults):
    return pyparsing.ParseResults.List(toks.as_list())

# Tcl dumps often leave representational errors
# A p4 data element is 1/16 scaled, 0.0625
def round2four(toks):
    val = toks[0] if isinstance(toks, pyparsing.ParseResults) else toks
    val = round(val, 4)
    ival = int(val)
    return ival if val == ival else val

### Start of Grammar ###

# This won't handle braces in the words
word_nb = Word(printables, exclude_chars='{}')

rounded_number = common.number.copy().add_parse_action(round2four)

braced_string = (
      Suppress('{')
    + original_text_for(ZeroOrMore(word_nb))
    + Suppress('}')
)

valid_key = common.identifier

valid_simple_value = (
    rounded_number
    | word_nb
    | braced_string
)

shot_frame = (
      Suppress('{')
    + dict_of(valid_key, valid_simple_value)
    + Suppress('}')
)

shot_frame_as_dict = shot_frame.copy().set_parse_action(dict)

list_of_shot_frames = \
    OneOrMore(shot_frame_as_dict).set_parse_action(pr_as_list)

shot_frame_list =  (
      Suppress('{')
    + list_of_shot_frames
    + Suppress('}')
)

valid_profile_value = (
      common.number
    | word_nb
    | shot_frame_list
    | braced_string
)


profile_dict = dict_of(valid_key, valid_profile_value)

### End of Grammar ###

def parsed_step_to_dict_v2(p_step: dict) -> dict:

    # p16 representation is 1/16 = 0.0625
    # so round to 4 digits to kill Tcl string errors

    # Pre-populate for readable order in JSON
    # will remove any None-valued from the step
    step_v2 = {
        'name':         p_step['name'],
        'pump':         p_step['pump'],
        'pressure':     None,
        'flow':         None,
        'limiter':      None,
        'transition':   p_step['transition'],
        'exit':         None,
        'weight':       None,
        'volume':       None,
        'seconds':      None,
        'temperature':  p_step['temperature'],
        'sensor':       p_step['sensor'],
    }

    if p_step['pump'] == 'pressure':
        step_v2['pressure'] = p_step['pressure']
    elif p_step['pump'] == 'flow':
        step_v2['flow'] = p_step['flow']
    else:
        raise ValueError(
            f"Unrecognized 'pump' type, '{p_step['pump']}")

    for move_on in ('seconds', 'volume', 'weight'):
        try:
            val = p_step[move_on]
            if val:
                step_v2[move_on] = val
        except KeyError:
            pass

    if p_step['exit_if']:
        exit_dict = dict()
        exit_type = p_step['exit_type']

        if exit_type == 'pressure_over':
            exit_dict['type'] = 'pressure'
            exit_dict['condition'] = 'over'
            exit_dict['value'] = p_step['exit_pressure_over']

        elif exit_type == 'pressure_under':
            exit_dict['type'] = 'pressure'
            exit_dict['condition'] = 'under'
            exit_dict['value'] = p_step['exit_pressure_under']

        elif exit_type == 'flow_over':
            exit_dict['type'] = 'flow'
            exit_dict['condition'] = 'over'
            exit_dict['value'] = p_step['exit_flow_over']

        elif exit_type == 'flow_under':
            exit_dict['type'] = 'flow'
            exit_dict['condition'] = 'under'
            exit_dict['value'] = p_step['exit_flow_under']

        else:
            raise ValueError(
                f"Unrecognized 'exit_type' {exit_type}")

        if exit_dict:
            step_v2['exit'] = exit_dict

    try:
        limiter_value = p_step['max_flow_or_pressure']
        if limiter_value:
            step_v2['limiter'] = {
                'value': limiter_value,
                'range': p_step['max_flow_or_pressure_range']
            }

    except KeyError:
        pass

    for k,v in step_v2.copy().items():
        if v is None:
            del step_v2[k]

    return step_v2


def parsed_dict_to_dict_v2(parsed: dict) -> dict:

    dict_v2 = {
        'version': VERSION['format'],
        'title': None,
        'notes': None,
        'author': None,
        'beverage_type': None,
        'steps': list(),
        'target_volume': None,
        'target_weight': None,
        'target_volume_count_start': None,
        'tank_temperature': None,
        'reference_file': None, # Eventually pick up from input file name
    }

    v2_key_map = {
        'author': 'author',
        'profile_title': 'title',
        'profile_notes': 'notes',
        'beverage_type': 'beverage_type',
        'tank_desired_water_temperature': 'tank_temperature',
        'final_desired_shot_weight_advanced': 'target_weight',
        'final_desired_shot_volume_advanced': 'target_volume',
        'final_desired_shot_volume_advanced_count_start':
            'target_volume_count_start',
        'settings_profile_type': 'legacy_profile_type',
        # 'type':	                            'type',	# 'advanced'
        'profile_language': 'lang',
        # 'profile_hide':	                    'hidden',	# 0/1
        # 'reference_file':	                    'reference_file',
        # 'changes_since_last_espresso':	    'changes_since_last_espresso',	# {}
        #                                       'version'   # 2,
    }

    for k,v in parsed.items():
        try:
            dict_v2[v2_key_map[k]] = v
        except KeyError:
            pass

    steps = dict_v2['steps']

    # A bit of history -- the types were named by John
    # based on the name the "screen" on which they were edited

    temperature_adjust_frame_time = 2  # seconds

    if parsed['settings_profile_type'] in ('settings_2c', 'settings_2c2'):
        dict_v2['type'] = 'advanced'
        for step in parsed['advanced_shot']:
            steps.append(parsed_step_to_dict_v2(step))

    elif parsed['settings_profile_type'] in ('settings_2a', 'settings_2b'):


        # espresso_temperature_0
        # need some parameter for frame 0 duration

        if parsed['espresso_temperature_1'] == parsed['espresso_temperature_0']:
            frame_0_duration = 0
        else:
            frame_0_duration = temperature_adjust_frame_time

        if parsed['preinfusion_time'] > frame_0_duration:
            frame_1_duration = round2four(
                parsed['preinfusion_time'] - frame_0_duration
            )
        else:
            frame_1_duration = 0

        steps = list()
        non_flow_frame_count = 0

        if frame_0_duration:
            steps.append(
                {
                    'name': 'temperature adj',
                    'pump': 'flow',
                    'flow': parsed['preinfusion_flow_rate'],
                    'transition': 'fast',
                    'exit': {
                        'type': 'pressure',
                        'condition': 'over',
                        'value': parsed['preinfusion_stop_pressure'],
                    },
                    'seconds': frame_0_duration,
                    'temperature': parsed['espresso_temperature_0'],
                    'sensor': 'coffee'
                },
            )
            non_flow_frame_count += 1

        if frame_1_duration:
            steps.append(
                {
                    'name': 'preinfuse',
                    'pump': 'flow',
                    'flow': parsed['preinfusion_flow_rate'],
                    'transition': 'fast',
                    'exit': {
                        'type': 'pressure',
                        'condition': 'over',
                        'value': parsed['preinfusion_stop_pressure'],
                    },
                    'seconds': frame_1_duration,
                    'temperature': parsed['espresso_temperature_1'],
                    'sensor': 'coffee'
                },
            )
            non_flow_frame_count += 1

            if parsed['settings_profile_type'] == 'settings_2a':

                dict_v2['type'] = 'pressure'
                if parsed['espresso_hold_time']:
                    steps.append(
                        {
                            'name': 'rise and hold',
                            'pump': 'pressure',
                            'pressure': parsed['espresso_pressure'],
                            'transition': 'smooth',
                            'limiter': {
                                'value': parsed['maximum_flow'],
                                'range': parsed['maximum_flow_range_default'],
                            },
                            'seconds': parsed['espresso_hold_time'],
                            'temperature': parsed['espresso_temperature_2'],
                            'sensor': 'coffee'
                        },
                    )

                if parsed['espresso_decline_time']:
                    steps.append(
                        {
                            'name': 'decline',
                            'pump': 'pressure',
                            'pressure': parsed['espresso_pressure'],
                            'transition': 'smooth',
                            'limiter': {
                                'value': parsed['maximum_flow'],
                                'range': parsed['maximum_flow_range_default'],
                            },
                            'seconds': parsed['espresso_decline_time'],
                            'temperature': parsed['espresso_temperature_3'],
                            'sensor': 'coffee'
                        },
                    )

            elif parsed['settings_profile_type'] == 'settings_2b':
                dict_v2['type'] = 'flow'

                if parsed['espresso_hold_time']:
                    steps.append(
                        {
                            'name': 'rise and hold',
                            'pump': 'flow',
                            'flow': parsed['flow_profile_hold'],
                            'transition': 'smooth',
                            'limiter': {
                                'value': parsed['maximum_pressure'],
                                'range': parsed[
                                    'maximum_pressure_range_default'],
                            },
                            'seconds': parsed['espresso_hold_time'],
                            'temperature': parsed['espresso_temperature_2'],
                            'sensor': 'coffee'
                        },
                    )

                if parsed['espresso_decline_time']:
                    steps.append(
                        {
                            'name': 'decline',
                            'pump': 'flow',
                            'flow': parsed['flow_profile_decline'],
                            'transition': 'smooth',
                            'limiter': {
                                'value': parsed['maximum_pressure'],
                                'range': parsed[
                                    'maximum_pressure_range_default'],
                            },
                            'seconds': parsed['espresso_decline_time'],
                            'temperature': parsed['espresso_temperature_3'],
                            'sensor': 'coffee'
                        },
                    )

            for step in steps:
                try:
                    if not step['limiter']['value']:
                        del step['limiter']
                except KeyError:
                    pass

            dict_v2['steps'] = steps
            dict_v2['target_volume_count_start'] = non_flow_frame_count
            dict_v2['target_volume'] = parsed['final_desired_shot_volume']
            dict_v2['target_weight'] = parsed['final_desired_shot_weight']

    dict_v2['creator'] = {
        'name': THIS_FILENAME,
        'version': VERSION['app'],
        'timestamp': TIMESTAMP,
    }


    return dict_v2


def dict_v2_set_author(dict_v2: dict[str], author: str):
    dict_v2['author'] = author


def dict_v2_set_reference_file(dict_v2: dict[str], filename: str):
    dict_v2['reference_file'] = filename


def dict_v2_get_title(dict_v2: dict[str]):
    return dict_v2['title']


def sanitize_filename(fname: str):
    return re.sub('[^\w._-]', '_', fname)


if __name__ == '__main__':

    import argparse
    import json
    import logging
    import sys

    from os.path import basename
    from pathlib import PurePath

    import requests

    ap = argparse.ArgumentParser(
        description="Executable to open a Tcl profile file "
                    f"and write as JSON v{VERSION['format']}. "
                    "Input and output default to STDIN and STDOUT"
    )
    ap.add_argument('-a', '--author',
                    help='Replace author')
    input_group = ap.add_mutually_exclusive_group()
    input_group.add_argument('-i', '--input', help='Input file')
    input_group.add_argument('-v', '--visualizer',
                             help='Visualizer short code or profile URL')
    ap.add_argument('-o', '--output', help='Output file')
    ap.add_argument('-d', '--dir', help='Output directory')
    ap.add_argument('-f', '--force', action='store_true',
                    help='Overwrite if output exists')
    args = ap.parse_args()

    logger = logging.getLogger()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s")

    initial_handler = logging.StreamHandler(stream=sys.stderr)
    initial_handler.setFormatter(formatter)
    initial_handler.setLevel(logging.DEBUG)
    initial_handler.name = 'initial_logger'

    logger.addHandler(initial_handler)
    logger.setLevel(logging.DEBUG)


    ref_file = None

    if args.input is not None:
        ref_file = args.input
        with open(args.input, 'r') as fh:
            source_data = fh.read()

    elif args.visualizer is not None:
        if len(args.visualizer) == 4:
            code = args.visualizer
            # short code, get the JSON, then get the profile_url
            logger.info(f"Getting shotdescription for {code}")
            req_by_code = requests.get(
                f'https://visualizer.coffee/api/shots/shared?code={code}')
            req_by_code.raise_for_status()
            shot_json = req_by_code.json()
            profile_url = shot_json['profile_url']
        else:
            profile_url = args.visualizer
        ref_file = profile_url
        logger.info(f"Getting {profile_url}")
        req = requests.get(url=profile_url)
        req.raise_for_status()
        source_data = req.text

    else:
        ref_file = None
        source_data = sys.stdin.read()

    pd_result = profile_dict.search_string(source_data)

    if len(pd_result) == 0:
        raise ValueError("No profile description found")
    elif len(pd_result) > 1:
        logging.error(
            "Multiple profile descriptions found. Ignoring all except first")
    pdd = dict(pd_result[0])
    dv2 = parsed_dict_to_dict_v2(pdd)

    if args.author is not None:
        dict_v2_set_author(dv2, args.author)

    if ref_file is not None:
        dict_v2_set_reference_file(dv2, ref_file)

    # Output file names:
    #
    # I V O D
    # -------
    #           stdout              0
    #       D   dir/<title>.json
    #     O     output              2
    #     O D   dir/output          1
    #   V       stdout              0
    #   V   D   dir/<title>.json
    #   V O     output              2
    #   V 0 D   dir/output          1
    # I         stdout              0
    # I     D   dir/input.json      3
    # I   O     output              2
    # I   O D   dir/output          1
    # I V x x   Not possible        -

    # Rule 0 -- to stdout
    if args.output is None and args.dir is None:
        fname = None
        print(json.dumps(dv2, indent=2), file=sys.stdout)

    # Rule 1 -- to dir/output
    elif args.output is not None:
        fname = PurePath(args.dir, args.output)

    # Rule 2 -- to output
    elif args.output is not None:
        fname = args.output

    # Rule 3 -- from input name to dir
    elif args.input is not None:
        fname = PurePath(args.dir, basename(args.input)).with_suffix('.json')

    else:
        profile_name = dict_v2_get_title(dv2)
        fname = sanitize_filename(profile_name) + '.json'


    if fname is not None:
        if os.path.exists(fname):
            if args.force:
                logger.warning(f"Overwriting {fname}")
            else:
                raise FileExistsError(fname)
        with open(fname, 'w') as fh:
            print(json.dumps(dv2, indent=2), file=fh)
        logger.info(f"Output written to {fname}")
