/** Copyright © 2023 Jeff Kletsky. All Rights Reserved.
 *
 * License for this software, part of the pyDE1 package, is granted under
 * GNU General Public License v3.0 only
 * SPDX-License-Identifier: GPL-3.0-only
 */

export const VERSION = '2.1';
export const SPEC_REVISION = '2.1';

/** This file has a primary purpose of documenting the pyDE1 profile format
 *
 *  Credit and appreciation to Mimoja for the initial implementation
 *  of JSON profiles in the de1app (TCL).
 *
 *  This definition removes most redundant and contextually meaningless
 *  information in the TCL representation of Buckman. Buckman's implementation
 *  tied the data structure and naming to the UI implementation in de1app.
 *  This implementation retains some legacy fields that de1app apparently needs
 *  to be able to select an editor for a profile. It also extends
 *  Mimoja's implementation with additional metadata related to
 *  the source of the profile and how and when it was created.
 *
 *  Implementations MAY be tolerant of the presence of extra fields
 *  that may have been written by other tools.
 *
 *  TypeScript was selected as a reasonable documentation format.
 *  This document has not been validated in a TypeScript project.
 *
 *  Limitations on the range of numeric values is not specified here.
 *
 *  Please report any issues or points that need clarification.
 */

/** NB: TCL does not discriminate between the number 5.3 and the string "5.3".
 *      As a result, JSON written by de1app writes a string rather than a number.
 *
 *      Implementations that read de1app-generated JSON profiles MAY be robust
 *      to this representation. However, any JSON written SHOULD be compliant
 *      with JSON standards and represent numbers as numbers, not strings.
 */

export type NonEmptyArray<T> = [T, ...T[]];

export type PumpType = 'pressure' | 'flow';
export type MoveOnType = 'seconds' | 'volume' | 'weight';
export type ExitType = 'pressure' | 'flow';
export type ExitCondition = 'over' | 'under';
export type TransitionType = 'fast' | 'smooth';
export type TemperatureSensor = 'coffee' | 'water';

/** A loose labeling of the general category of the intent of the profile.
 *  Potentially can be extended by users. Primarily used for skipping upload
 *  to Visualizer and for categorization in DYE, Visualizer, and others. */
export type BeverageType =
    'espresso'
    | 'calibrate'
    | 'cleaning'
    | 'manual'
    | 'pourover'
    | 'tea_portafilter';

/** Buckman tied profile type to the name of the UI screen
 *  on which it was edited. See also type ProfileEditor */
export type LegacyProfileType =
    'settings_2a'
    | 'settings_2b'
    | 'settings_2c'
    | 'settings_2c2';

/** A normalization of LegacyProfileType.
 *  Does not impact how the DE1 operates. */
export type ProfileEditor = 'advanced' | 'flow' | 'pressure';

export type ISOTimestamp = string
export type SemanticVersion = string

export interface ProfileJSON {
    /** Identifies the semantic version of the JSON format, presently 2.1 */
    version: SemanticVersion;
    /** A one-line string that can identify the profile to a user */
    title: string;
    /** A longer description of the profile and/or its use
     *  that can be multi-line */
    notes: string;
    /** The author of the profile.
     *  NB: "Decent" is likely inappropriately present
     *  for user-generated profiles */
    author: string;
    /** A general category for the beverage or function.
     *  Used by DYE, Visualizer uploaders, and others */
    beverage_type: BeverageType;
    /** An array of one or more steps or frames describing the actions
     *  the DE1 should take */
    steps: NonEmptyArray<ProfileStep>
    /** If non-zero and non-null, the estimated volume
     *  at which the DE1 should stop */
    target_volume: number | null;
    /** If non-zero and non-null, the weight
     *  at which the DE1 should be stopped */
    target_weight: number | null;
    /** An integer indicating the zero-based frame number after which to start
     *  the "pour" accounting of time and volume */
    target_volume_count_start: number;
    /** If non-zero, the target temperature in °C to which the tank
     *  should be heated prior to starting the frames. */
    tank_temperature: number;
    /** Legacy field from de1app profiles, seemingly all contain "en" */
    lang: string;
    /** Legacy identifier in the de1app */
    legacy_profile_type: LegacyProfileType;
    /** Legacy style of de1app editor to display or edit the profile */
    type: ProfileEditor;
    /** A reference to the source of the profile.
     *  The field is present but often the empty string from de1app */
    reference_file: string;
    /** An optional descriptor of how and when this version was generated */
    creator?: CreatorData;
}

export type ProfileStep = ProfileStepPressure | ProfileStepFlow;

export interface ProfileStepBase {
    /** A label suitable for rendering in a UI */
    name: string;
    /** How the target over time should move from the controlled variable
     *  at the start of the frame (at run time) to the target for this frame */
    transition: TransitionType;
    /** An optional exit condition based on flow or pressure */
    exit?: StepExitConditition;
    /** The volume in mL dispensed in this fram over which
     *  the frame would be exited, */
    volume: number;
    /** The duration of this frame over which the frame would be exited */
    seconds: number;
    /** If present, the weight in g over which the frame would be exited */
    weight?: number;
    /** The target temperature in °C for this frame. See also sensor: */
    temperature: number;
    /** The sensor to use to measure temperature for this frame */
    sensor: TemperatureSensor;
}

export interface ProfileStepPressure extends ProfileStepBase {
    /** Defines this as a pressure-driven step */
    pump: 'pressure';
    /** The target pressure in bar */
    pressure: number;
}

export interface ProfileStepFlow extends ProfileStepBase {
    /** Defines this as a flow-driven step */
    pump: 'flow';
    /** The target flow in mL/s */
    flow: number;
}

export interface StepExitConditition {
    /** Exit based on flow or pressure. Omit StepExitCondition otherwise */
    type: ExitType;
    /** Is the exit to occur when the measured value crosses the threshold
     *  from above or from below. */
    condition: ExitCondition;
    /** The numeric threshold */
    value: number;
}

/** See current DE1 documentation on how the Limiter parameters impact operation.
 *  At least at this time, pressure-driven and flow-driven profiles
 *  behave differently. The description is the same in the profile for both. */
export interface Limiter {
    value: number;
    range: number
}

export interface CreatorData {
    /** A reference to the product name or utility */
    name: string;
    /** An identifier string of the version of the product or utility
     *  Although semantic versioning is preferred, it is not required. */
    version: string;
    /** An ISO timestamp of when the conversion was performed.
     *  Should include full date, time with at least seconds, and timezone */
    timestamp: ISOTimestamp;
}

