"""
Copyright © 2022-2023 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

from pyDE1.services.runnable.legacy_to_json import (
    braced_string,
    valid_key, valid_simple_value, shot_frame, shot_frame_list,
)


def show_test_result(result):
    if result[0]:
        print("\n-------\nPASSED\n-------\n")
    else:
        print("\n=======\nFAILED\n=======\n")
    assert result[0]


def test_braced_string():
    result = braced_string.run_tests(
        tests="""
        {}
        {one}
        {two words}
        { one }
        { two words }
        """
    )
    show_test_result(result)

    result = braced_string.run_tests(
        failure_tests=True,
        tests="""
        { word {with internal brace} mess }
        # Embedded {one} word
        """
    )
    show_test_result(result)


def test_valid_key():
    result = valid_key.run_tests(
        tests="""
        word
        advanced_shot
        maximum_pressure_range_advanced
        """
    )
    show_test_result(result)

    result = valid_key.run_tests(
        failure_tests=True,
        tests="""
        two words
        {word}
        0
        3.4
        [foo]
        Downloaded from Visualizer}
        """
    )
    show_test_result(result)


def test_valid_simple_value():
    result = valid_simple_value.run_tests(
        tests="""
        word
        {}
        {one}
        {two words}
        {Extractamundo Tres!}
        0
        -1
        1.2
        {0}
        {1.2}
        { 1.2 }
        {-3}
        { -4.5}
        """
    )
    show_test_result(result)

    result = valid_simple_value.run_tests(
        failure_tests=True,
        tests="""
        two words
        { word {with internal brace} mess }
        Embedded {one} word
        """
    )
    show_test_result(result)


def test_valid_shot_frame():
    test_data = [
        "{simple frame number 1}",
        "{simple frame number 2}",

        "{exit_if 1 flow 8.0 volume 100 max_flow_or_pressure_range 3.0 "
        "transition fast exit_flow_under 0 temperature 85.5 name {temp comp} "
        "pressure 8.0 sensor coffee pump pressure exit_type pressure_over "
        "exit_flow_over 6 exit_pressure_over 5.00 max_flow_or_pressure 0 "
        "exit_pressure_under 0 seconds 2.00}",

        "{exit_if 1 flow 8.0 volume 100 max_flow_or_pressure_range 3.0 "
        "transition fast exit_flow_under 0 temperature 80.5 weight 10.00 name "
        "preinfusion pressure 8.0 pump pressure sensor coffee exit_type "
        "pressure_over exit_flow_over 6 exit_pressure_over 5.00 "
        "max_flow_or_pressure 0 exit_pressure_under 0 seconds 20.00}",
    ]
    result = shot_frame.run_tests(
        full_dump=False,
        tests=test_data,
    )
    show_test_result(result)

    result = shot_frame.run_tests(
        failure_tests=True,
        full_dump=False,
        tests=[
            ' '.join(test_data[0:2]),
            ' '.join(test_data[2:4]),
        ],
    )
    show_test_result(result)


def test_valid_shot_frame_list():
    test_data = [
        "{{simple frame number 1}}",
        "{{simple frame number 1}{simple frame number 2}}",
        "{{simple frame number 1} {simple frame number 2}}",

        " {{exit_if 1 flow 8.0 volume 100 max_flow_or_pressure_range 3.0 "
        "transition fast exit_flow_under 0 temperature 85.5 name {temp comp} "
        "pressure 8.0 sensor coffee pump pressure exit_type pressure_over "
        "exit_flow_over 6 exit_pressure_over 5.00 max_flow_or_pressure 0 "
        "exit_pressure_under 0 seconds 2.00} {exit_if 1 flow 8.0 volume 100 "
        "max_flow_or_pressure_range 3.0 transition fast exit_flow_under 0 "
        "temperature 80.5 weight 10.00 name preinfusion pressure 8.0 pump "
        "pressure sensor coffee exit_type pressure_over exit_flow_over 6 "
        "exit_pressure_over 5.00 max_flow_or_pressure 0 exit_pressure_under "
        "0 seconds 20.00} {exit_if 1 flow 0 volume 100 "
        "max_flow_or_pressure_range 5.0 transition fast exit_flow_under 0 "
        "temperature 60.5 name {dynamic bloom} pressure 6.0 sensor coffee pump "
        "flow exit_type pressure_under exit_flow_over 6 max_flow_or_pressure 0 "
        "exit_pressure_over 11 exit_pressure_under 2.20 seconds 40.00} "
        "{exit_if 0 flow 6.0 volume 100 max_flow_or_pressure_range 5.0 "
        "transition fast exit_flow_under 0 temperature 60.5 name {6 mlps} "
        "pressure 6.0000000000000036 sensor coffee pump flow exit_type "
        "flow_under exit_flow_over 6 max_flow_or_pressure 2.0 "
        "exit_pressure_over 11 exit_pressure_under 0 seconds 60.00}}",
    ]
    test_data_fail = [
        "{}",
        "{{}}",

        "{exit_if 1 flow 8.0 volume 100 max_flow_or_pressure_range 3.0 "
        "transition fast exit_flow_under 0 temperature 85.5 name {temp comp} "
        "pressure 8.0 sensor coffee pump pressure exit_type pressure_over "
        "exit_flow_over 6 exit_pressure_over 5.00 max_flow_or_pressure 0 "
        "exit_pressure_under 0 seconds 2.00}",
    ]
    result = shot_frame_list.run_tests(
        # full_dump=False,
        tests=test_data,
    )
    show_test_result(result)

    result = shot_frame_list.run_tests(
        failure_tests=True,
        full_dump=False,
        tests=test_data_fail,
    )
    show_test_result(result)



