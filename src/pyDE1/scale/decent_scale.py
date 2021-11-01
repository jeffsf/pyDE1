"""
Copyright © 2021 Andrew Bromell.
Copyright © 2021 Jeff Kletsky,
All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

================================================================================
Implemented per the Decent Scale v1.0 API spec found at:
   https://decentespresso.com/decentscale_api
and as per firmware bugs marked therein or via communication on Decent's
Basecamp forum (which is more up to date than the API documentation).

NB: There will be some differences for API v1.1 which will break some v1.0
operations.  There will be a way to confirm the API version of the scale
remotely in v1.1, but until this mechanism is known, the user should confirm
the scale in use is v1.0 or wait for a release that explicitly caters for any
firmware version beyond v1.0.

--- Decent Scale communication overview ---
 - Scale communicates via bluetooth, with all commands on one common cuuid,
   and all messages back from the scale on another
 - Any commands sent to the scale will (excepting bugs in firmware) be
   followed by a positive confirmation message sent back by the scale if
   execution was successful
 - Weight updates will automatically be broadcast once the scale is connected
   and any successful command has been sent and acted upon by the scale
 - All messages (inbound or outbound) have the same basic 7 byte structure:
        1 Model - which is always 03 for the Decent Scale v1.0
        2 Command
        3 Data byte 1
        4 Data byte 2
        5 Data byte 3
        6 Data byte 4
        7 Checksum - Serialised byte-by-byte XOR of the first 6 bytes

--- Other key notes ---
 - Scale's timer functionality has been ignored as (a) it's not supported by
   pyDE1, (b) there are better sources of timing available to pyDE1, and (c)
   any GUI will be able to display said superior timing to the user.
================================================================================
"""

import asyncio
import enum
import sys
import time
from typing import Callable, Union

import pyDE1
from pyDE1.scale import Scale
from pyDE1.scale.events import ScaleWeightUpdate, ScaleButtonPress
from pyDE1.utils import data_as_hex

logger = pyDE1.getLogger('Scale.DecentScale')


class DecentScale(Scale):

    def __init__(self):
        super(DecentScale, self).__init__()

        # --- General setup ---
        # Decent Scale sends weight updates at 10Hz
        self._nominal_period = 0.1

        # jmk -- leaving this as it determines the timing in the FlowSequencer
        #        and am removing the retry here. Either the scale tares,
        #        or it doesn't. The FlowSequencer will take care of it
        #        during a sequence. Dealing with it from a button will be
        #        annoying, and will likely require a mutex
        self._minimum_tare_request_interval = 2.5 * self._nominal_period

        # seconds, including all transit delays
        # TODO:Determine correct value experimentally for Decent Scale v1.0
        self._sensor_lag = 0.4

        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"

        # jmk -- The Decent Scale apparently always sends weight and button
        #        updates. These flags determine if to generate events when
        #        they arrive.
        self._send_weight_events = False
        self._send_button_events = False

        # --- Tare setup ---
        # Enable tare by pressing the button on the scale, hold UUID if need to
        # unsubscribe
        self._button_tare_subscriber_id = None
        asyncio.get_event_loop().create_task(self._subscribe_button_press())

        # Linux, at least on an RPi 3B, needs response=True for write_gatt_char
        # TODO:Confirm if required for Decent Scale (assumption is yes)
        self._write_gatt_char_response = sys.platform == 'linux'

    async def standard_initialization(self, hold_notification=False):
        # jmk -- Here is where the CUUID listener needs to go
        await self._bleak_client.start_notify(CUUID.READ.value,
                                              self._create_message_handler())
        await super(DecentScale, self).standard_initialization(
            hold_notification=True)
        if not hold_notification:
            await self._notify_ready()

    async def start_sending_weight_updates(self):
        # jmk -- TODO: connection-aware
        self._send_weight_events = True
        logger.info("Sending weight updates")

    async def stop_sending_weight_updates(self):
        # jmk -- TODO: connection-aware
        self._send_weight_events = False
        logger.info("Stopped weight updates")

    def is_sending_weight_updates(self):
        # jmk -- just because it was asked to, doesn't mean that it is
        # jmk -- Might be implemented in the future for multiple scales
        #        Not in use as this time
        return NotImplementedError

    # TODO: Consider adding additional logic to capture the most recent weight
    #       and timestamp, and if still fresh, return it here.  Seems redundant
    #       though given this data is flooding through constantly if on.
    # jmk -- Might be implemented in the future for multiple scales
    #        Not in use as this time
    async def current_weight(self):
        raise NotImplementedError

    # jmk -- If the scale doesn't work right when running on a sane BLE stack
    #        we'll deal with it later. That it is conveniently not decoupling
    #        local, button-driven tare when connected means that, hopefully,
    #        tare will take care of itself from the button. The FlowSequencer
    #        will cover the hold-at-zero behavior, without resorting to another
    #        task to monitor. A late tare is problematic as it may be into
    #        a period where it is expected that the weight will be increasing.
    #        Display on/off I'm less worried about as it typically isn't
    #        a time-sensitive action. I'd rather not assume that we've got to
    #        add a mutex everywhere and schedule tasks to keep retrying.

    async def _tare_internal(self):
        await self._bleak_client.write_gatt_char(
            CUUID.WRITE.value,
            PackedCommand.TARE.value,
            response=self._write_gatt_char_response)
        logger.info("Internal tare sent")

    async def display_on(self):
        await self._bleak_client.write_gatt_char(
            CUUID.WRITE.value,
            PackedCommand.DISPLAY_ON.value,
            response=self._write_gatt_char_response)
        logger.info("Display on")

    async def display_off(self):
        await self._bleak_client.write_gatt_char(
            CUUID.WRITE.value,
            PackedCommand.DISPLAY_OFF.value,
            response=self._write_gatt_char_response)
        logger.info("Display off")

    async def set_grams(self):
        # This function is not available via the v1.0 API for the Decent scale.
        # Apparently will be available in v1.1.
        raise NotImplementedError

    @property
    def supports_button_press(self):
        return True

    async def start_sending_button_updates(self):
        # jmk -- TODO: connection-aware
        self._send_button_events = True
        logger.info("Sending button updates")

    async def stop_sending_button_updates(self):
        # jmk -- TODO: connection-aware
        self._send_button_events = False
        logger.info("Stopped button updates")

    # As the Decent Scale sends all message types on the same cuuid, this is a
    # centralised handler to decipher the message type and act appropriately
    # (or broadcast an event for others to do so)
    def _create_message_handler(self) -> Callable:
        scale = self

        async def message_handler(sender, data):
            nonlocal scale

            now = time.time()

            # Byte 7 of the message is a checksum of the first 6 - ensure it
            # checks out

            if (ld := len(data)) != 7:
                logger.error(
                    f"Scale payload {ld} bytes, expected 7. Skipping")

            elif not confirm_trailing_checksum(data):
                logger.error(
                    f"Invalid checksum in {data_as_hex(data)}, Skipping")

            elif (model := data[0]) != 0x03:
                logger.error(
                    f"Invalid model byte, 0x{model:02x}, Skipping")

            else:
                # Determine message type (stored in byte 2) and action

                try:
                    command = Command(data[1])
                except ValueError:
                    command = None

                if command in (Command.WEIGHT_STABLE, Command.WEIGHT_CHANGING):
                    # Per API advice, ignoring the "change in weight" data
                    # as dodgy.

                    if self._send_weight_events:
                        self._update_scale_time_estimator(now)

                        w = int.from_bytes(data[2:4],
                                           'big',
                                           signed=True) / 10.0

                        await scale.event_weight_update.publish(
                            ScaleWeightUpdate(
                                arrival_time=now,
                                scale_time=self._scale_time_from_latest_arrival(now),
                                weight=w)
                        )

                elif command == Command.BUTTON_TAP:
                    if self._send_button_events:
                        try:
                            shape = Button(data[2])
                        except ValueError:
                            shape = None
                            logger.error(
                                f"Invalid button shape: {data[2]}, skipping")
                        try:
                            duration = ButtonDuration(data[3])
                        except ValueError:
                            duration = None
                            logger.error(
                                f"Invalid button duration: {data[3]}, skipping")
                        if shape and duration:  # jmk - works as neither is 0

                        # The Decent Scale sends byte 3 to indicate the button
                        # pressed.  It also sends byte 4 to indicate a short
                        # tap or long press.  For simplicity with the Scale
                        # class' standardised interface, these have been
                        # combined into a single 2 bit value:
                        # BUTTON_CIRCLE & SHORT_TAP  = \b00 = 0
                        # BUTTON_CIRCLE & LONG_PRESS = \b01 = 1
                        # BUTTON_SQUARE & SHORT_TAP  = \b10 = 2
                        # BUTTON_SQUARE & LONG_PRESS = \b11 = 3

                        # jmk -- I like the idea here.
                        #        I'd pack these so that there's an easy test
                        #        for "button 1, short or long" or "any long"
                        #
                        #        As they're already packed, I'll just pass them

                        # jmk -- Meh, not thrilled about that idea, here's
                        #        going back four buttons, but numbered 1,2
                        #        then 3,4 for the long presses.

                            if shape == Button.CIRCLE:
                                if duration == ButtonDuration.SHORT:
                                    bm = ButtonMapped.CIRCLE_SHORT
                                else:
                                    bm = ButtonMapped.CIRCLE_LONG
                            else:
                                if duration == ButtonDuration.SHORT:
                                    bm = ButtonMapped.SQUARE_SHORT
                                else:
                                    bm = ButtonMapped.SQUARE_LONG

                            sbp = ScaleButtonPress(arrival_time=now,
                                                   button=bm)
                            await scale.event_button_press.publish(sbp)

                elif command == Command.TIMER:
                    # Not supported by pyDE1, nor relevant given much better
                    # quality sources of timing exist
                    pass

                elif command in (Command.TARE_RESPONSE,
                                 Command.DISPLAY_RESPONSE):
                    logger.info(f"{command} received")

                else:  # unknown
                    logger.error(
                        f"Unrecognized scale message type, {command}, skipping"
                    )

        return message_handler

    # This is somewhat redundant for API v1.0 as the scale will self-tare
    # regardless of what the software says.  May still be valuable though, just
    # so that the dataset will show a tare command around the right time.  Will
    # also be important for API v1.1.  As such, retaining for now.

    # jmk -- If the scale is already flaky, asking for it to tare after
    #        it has already done so seems unhelpful

    async def _subscribe_button_press(self):
        scale = self

        logger.info("Starting button press handler")

        async def button_event_handler(sbp: ScaleButtonPress) -> None:
            nonlocal scale

            # jmk -- using the enum means no "magic numbers" to remember
            if sbp.button in (ButtonMapped.CIRCLE_SHORT,
                              ButtonMapped.CIRCLE_LONG):
                # await scale.tare()
                logger.info(
                    "Round button press noted. Scale probably set tare.")
            else:
                logger.debug(f"Button {sbp.button} - Not implemented")

        # noinspection PyTypeChecker
        self._button_tare_subscriber_id = \
            await self._event_button_press.subscribe(button_event_handler)


# As per Decent's spec, common Characteristic UUID's for all commands
class CUUID(enum.Enum):

    READ  = "0000fff4-0000-1000-8000-00805f9b34fb"  # Read data FROM scale
    WRITE = "000036f5-0000-1000-8000-00805f9b34fb"  # Write data TO scale


class Command (enum.IntEnum):

    DISPLAY_RESPONSE    = 0x0a
    TIMER               = 0x0c
    TARE_RESPONSE       = 0x0f
    BUTTON_TAP          = 0xaa
    WEIGHT_STABLE       = 0xce
    WEIGHT_CHANGING     = 0xca


# Outbound commands to the scale.  Given these are fixed in format, they do
# not need to be dynamically generated.

class PackedCommand(enum.Enum):

    # Only weight LEDs turned on with these commands. The timer display is
    # left off in both cases as it's not being used
    DISPLAY_ON  = b'\x03\x0a\x01\x00\x00\x00\x08'
    DISPLAY_OFF = b'\x03\x0a\x00\x00\x00\x00\x09'

    # Request scale to tare. Note that this is sufficient for v1.0 API due
    # to a firmware bug (i.e. can ignore setting a valid counter value in
    # byte 3)
    TARE        = b'\x03\x0f\x00\x00\x00\x00\x0c'

    # pyDE1 does not currently support timer functions, so these are unused
    # but left here for completeness in case this is enabled in the future
    # jmk -- the checksums appear to be wrong in these
    TIMER_ZERO  = b'\x03\x0b\x02\x00\x00\x00\x08'
    TIMER_START = b'\x03\x0b\x03\x00\x00\x00\x09'
    TIMER_STOP  = b'\x03\x0b\x00\x00\x00\x00\x0a'


class Button (enum.IntEnum):

    CIRCLE = 0x01
    SQUARE = 0x02


class ButtonDuration (enum.IntEnum):

    SHORT = 0x01
    LONG  = 0x02


class ButtonMapped (enum.IntEnum):
    CIRCLE_SHORT = 1
    SQUARE_SHORT = 2
    CIRCLE_LONG  = 3
    SQUARE_LONG  = 4


# NOTE: No longer required for v1.0 firmware due to bugs in said firmware.
#       Retaining as will probably be useful for v1.1 and onwards
# Per API, calculates the checksum required in byte 7 of a message as the
# byte-by-byte xor of six sequential bytes.  This code doesn't assume a
# specific length of the message, however.

# jmk -- No need to repeat the calculation code twice
def xor_checksum(some_bytes: Union[bytes, bytearray]):
    checksum = 0x00
    for b in some_bytes:
        checksum ^= b
    return checksum


def confirm_trailing_checksum(some_bytes: Union[bytes, bytearray]):
    if len(some_bytes) < 2:
        return False
    else:
        return some_bytes[-1] == xor_checksum(some_bytes[0:-2])


Scale.register_constructor(DecentScale, 'Decent Scale')
