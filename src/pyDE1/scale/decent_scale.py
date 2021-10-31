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
import logging
import sys
import time
from typing import Callable

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from pyDE1.scale import Scale
from pyDE1.scale.events import ScaleWeightUpdate, ScaleButtonPress

from pyDE1.event_manager import EventPayload, SubscribedEvent

logger = logging.getLogger('Scale.DecentScale')
logger.setLevel(logging.DEBUG)


# TODO: make use the DecentScale's MESSAGE class rather than generic type, if
#       practical
# Class to represent the event payload of a message received from the scale.
# Nominally used by Tare and Display responses as these aren't covered by
# existing generic events defined in
class ScaleResponse(EventPayload):
    def __init__(self, arrival_time: float, type: bytes, data: bytes):
        super(ScaleResponse, self).__init__(arrival_time=arrival_time)
        self.message_type = type
        self.message_data = data


class DecentScale(Scale):

    def __init__(self):
        super(DecentScale, self).__init__()

        # --- General setup ---
        # Decent Scale sends weight updates at 10Hz
        self._nominal_period = 0.1

        # seconds, including all transit delays
        # TODO:Determine correct value experimentally for Decent Scale v1.0
        self._sensor_lag = 0.4

        # Linux, at least on an RPi 3B, needs response=True for write_gatt_char
        # TODO:Confirm if required for Decent Scale (assumption is yes)
        self._write_gatt_char_response = sys.platform == 'linux'

        # Decent Scale sends messages in big endian byte format
        self._byte_order = 'big'

        # Attempt each command this many times before giving up; needs to be at
        # least 2 given quirks in the v1.0 firmware (first message sometimes
        # ignored).
        self._command_attempts = 3

        # TODO: Implement a check to confirm connected scale version and flag
        # TODO: error or warning (as appropriate) if unsupported (Depends on
        # TODO: version check mechanism to be confirmed in firmware v1.1)
        # Latest version of scale firmware this code has been tested for
        self._tested_api_version = "1.0"

        # Various status indicators for messages to resubmit as events
        self._message_handler_created = False
        self._send_weight_events = False
        self._send_button_events = False

        # --- Tare setup ---
        # Enable tare by pressing the button on the scale, hold UUID if need to
        # unsubscribe
        self._button_tare_subscriber_id = None
        asyncio.get_event_loop().create_task(self._subscribe_button_press())

        # Enable internal tare response events, hold UUID if need to unsubscribe
        self._event_tare_subscriber_id = None
        # TODO: work out what this really does, and if any cleanup required
        self._event_tare_response: SubscribedEvent = SubscribedEvent(self)

        # Grams, within this, considered "at zero"; official accuracy is to
        # nearest 0.1g, so 0.05 is correct as this is the median between ticks
        self._tare_threshold = 0.05

        # Time to wait before resending a request.
        # NB: Should normally take roughly half a cycle (~30-70ms), but in
        # extreme cases can take as high as 200ms (2 cycles) or more.
        # Aggressively setting limit to 150ms (1.5 cycles) is ok given the retry
        # attempts in sending commands, which compensates for any extremely
        # delayed response, and useful given retries are frequently necessary
        # due to a firmware bug in v1.0 scales (refer API documentation).
        self._minimum_tare_wait_interval = 0.15

        # Seconds until considered coincidence.  Note that this is
        # theoretically not required for the Decent Scale due to it sending an
        # explicit confirmation, but in practice this response is buggy so
        # makes sense to keep this as a backup for firmware v1.0
        self._tare_timeout = 1.0

        # Allows for 3 command retries with some buffer
        self._minimum_tare_request_interval = 5 * self._nominal_period

        # --- Display setup ---
        # Enable internal display response events, hold UUID if need to
        # unsubscribe
        self._event_display_subscriber_id = None
        # TODO: work out what this really does, and if any cleanup required
        self._event_display_response: SubscribedEvent = SubscribedEvent(self)

        # Time to wait before resending a request.
        # Seems to take around one second, but given firmware bugs, aggressively
        # resend command
        self._minimum_display_wait_interval = 0.15

    # As per Decent's spec, common Characteristic UUID's for all commands
    class _CUUID(enum.Enum):
        READ  = f"0000fff4-0000-1000-8000-00805f9b34fb"  # Read data FROM scale
        WRITE = f"000036f5-0000-1000-8000-00805f9b34fb"  # Write data TO scale

    # Outbound commands to the scale.  Given these are fixed in format, they do
    # not need to be dynamically generated.
    class _COMMAND(enum.Enum):
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
        # TIMER_ZERO  = b'\x03\x0b\x02\x00\x00\x00\x08'
        # TIMER_START = b'\x03\x0b\x03\x00\x00\x00\x09'
        # TIMER_STOP  = b'\x03\x0b\x00\x00\x00\x00\x0a'

    # Inbound message types from the scale
    # TODO:Make this work (declared in the handler at the moment)
    # class _Message(enum.Enum):
    #     WEIGHT_STABLE    = b'\xce'
    #     WEIGHT_CHANGING  = b'\xca'
    #     DISPLAY_RESPONSE = b'\x0a'
    #     TIMER            = b'\x0c'
    #     TARE_RESPONSE    = b'\x0f'
    #     BUTTON_TAP       = b'\xaa'

    # NOTE: No longer required for v1.0 firmware due to bugs in said firmware.
    #       Retaining as will probably be useful for v1.1 and onwards
    # Per API, calculates the checksum required in byte 7 of a message as the
    # byte-by-byte xor of six sequential bytes.  This code doesn't assume a
    # specific length of the message, however.
    # def calc_serial_byte_xor(self, byte_str):
    #     _xor = bytearray(b'\x00')
    #     _byte_array = bytearray(byte_str)
    #     i = 0
    #     while i < len(_byte_array):
    #         _xor[0] ^= _byte_array[i]
    #         i += 1
    #     return _xor

    # Per API, confirms that the checksum (byte 7 of a message) is the correct
    # serial byte-by-byte xor of the first 6 bytes.
    # TODO: Can this be internal (first char "_")?
    def check_serial_byte_xor(self, byte_array):
        _xor = bytearray(b'\x00')
        if len(byte_array) != 7:
            logger.warning(f"Message was not the required 7 bytes long, can't" +
                           " validate checksum: {byte_array}")
            return False
        i = 0
        while i < 6:
            _xor[0] ^= byte_array[i]
            i += 1
        return _xor[0] == byte_array[6]

    async def standard_initialization(self, hold_notification=False):
        await super(DecentScale, self).standard_initialization(
            hold_notification=True)
        if not hold_notification:
            await self._notify_ready()

        # create the message handler to parse all data coming from the scale
        if not self._message_handler_created:
            self._message_handler_created = True
            # create the message handler to parse all data coming from the scale
            await self._bleak_client.start_notify(self._CUUID.READ.value,
                                                 self._create_message_handler())

    async def disconnect(self):
        # dismantle the message handler
        await self._bleak_client.stop_notify(self._CUUID.READ.value)
        self._message_handler_created = False
        logger.info("Stopped message handler")

        # now call the standard disconnection routine
        await super(DecentScale, self).standard_initialization(
            hold_notification=True)

    async def start_sending_weight_updates(self):
        self._send_weight_events = True
        logger.info("Sending weight updates")

    async def stop_sending_weight_updates(self):
        self._send_weight_events = False
        logger.info("Stopped weight updates")

    def is_sending_weight_updates(self):
        return self._send_weight_events

    # TODO: Consider adding additional logic to capture the most recent weight
    #       and timestamp, and if still fresh, return it here.  Seems redundant
    #       though given this data is flooding through constantly if on.
    async def current_weight(self):
        raise NotImplementedError

    async def _tare_internal(self):
        attempts = self._command_attempts
        tare_response_received = False

        async def tare_response(response: ScaleResponse):
            nonlocal tare_response_received
            logger.debug(f"tare_response triggered with " +
                         "{response.message_data}")
            tare_response_received = True

        # Make sure the function above is listening for tare response events
        # from the message handler
        # noinspection PyTypeChecker
        self._event_tare_subscriber_id =\
            await self._event_tare_response.subscribe(tare_response)

        while attempts > 0:
            # make tare request
            # TODO: catch and deal with all relevant await exceptions
            await self._bleak_client.write_gatt_char(self._CUUID.WRITE.value,
                self._COMMAND.TARE.value,
                response=self._write_gatt_char_response)
            logger.debug(f"Tare request sent to scale, {attempts-1}" +
                         "attempt(s) remaining")

            # Now wait while a response comes in.  Should take roughly half a
            # cycle (~30-70ms), but in extreme cases can take as high as 140ms
            # (1.4 cycles).  Aggressively setting limit to 100ms (1 cycle) given
            # retries will compensate for any extremely delayed response, and
            # given retries are frequently necessary due to a firmware bug in
            # v1.0 scales (refer API documentation).
            try:
                await asyncio.sleep(self._minimum_tare_wait_interval)
            except asyncio.exceptions.CancelledError:
                # Not sure exactly why this might occur
                logger.debug("Sleep timer cancelled")

            # NB: this should have been updated by tare_response if a valid
            # message came back
            if tare_response_received:
                break
            else:
                logger.debug("Timed out waiting for a tare response to " +
                             "request attempt " +
                             f"{self._command_attempts - attempts + 1}" +
                             ", retrying...")
                attempts -= 1

        if attempts == 0:
            logger.info("Tare request failed")
        else:
            logger.info("Tare request succeeded")

        # TODO: make the subscribe/unsubscribe happen only once, and globally
        await self._event_tare_response.unsubscribe(
            self._event_tare_subscriber_id)

    # Internal display change command. Waits (async) for confirmation event that
    # the change was successful, as sent out by the inbound "message_handler".
    async def _display_change(self, on: bool):
        attempts = self._command_attempts
        display_response_received = False
        if on:
            state_str = "on"
        else:
            state_str = "off"

        # TODO: Investigate the display response.  Most of the time, they don't
        #       appear to come through.
        async def display_response(response: ScaleResponse):
            nonlocal display_response_received

            logger.debug("display_response triggered with " +
                         f"{response.message_data}")

            # The tare response from the scale doesn't include the command " +
            # "value as the API specifies, so just assume this response is the
            # right one
            display_response_received = True

        # Make sure the function above is listening for tare response events
        # from the message handler
        # noinspection PyTypeChecker
        self._event_display_subscriber_id =\
            await self._event_display_response.subscribe(display_response)

        while attempts > 0:
            # make display request
            if on:
                await self._bleak_client.write_gatt_char(
                    self._CUUID.WRITE.value,
                    self._COMMAND.DISPLAY_ON.value,
                    response=self._write_gatt_char_response)
            else:
                await self._bleak_client.write_gatt_char(
                    self._CUUID.WRITE.value,
                    self._COMMAND.DISPLAY_OFF.value,
                    response=self._write_gatt_char_response)

            logger.debug(f"Display {state_str} request sent to scale, " +
                         f"{attempts - 1} attempt(s) remaining")

            # Now wait while a response comes in
            try:
                await asyncio.sleep(self._minimum_display_wait_interval)
            except asyncio.exceptions.CancelledError:
                logger.debug("Sleep timer cancelled")

            # NB: this should have been updated by display_response if a valid
            # message came back
            if display_response_received:
                break
            else:
                logger.debug("Timed out waiting for a display response to " +
                             "request attempt " +
                             f"{self._command_attempts - attempts + 1}" +
                             ", retrying...")
                attempts -= 1

        if attempts == 0:
            # Due to firmware v1.0 bug, only ~10% of display responses are
            # actually sent back, hence can't assume failed if no response
            logger.info(f"Display {state_str} request was not confirmed; may " +
                        "have failed (but hard to know on v1.0 firmware)")
        else:
            logger.info(f"Display {state_str} request succeeded")

        # TODO: make the subscribe/unsubscribe happen only once, and globally
        await self._event_display_response.unsubscribe(
            self._event_display_subscriber_id)

    async def display_on(self):
        await self._display_change(True)

    async def display_off(self):
        await self._display_change(False)

    async def set_grams(self):
        # This function is not available via the v1.0 API for the Decent scale.
        # Apparently will be available in v1.1.
        raise NotImplementedError

    @property
    def supports_button_press(self):
        return True

    async def start_sending_button_updates(self):
        self._send_button_events = True
        logger.info("Sending button updates")

    async def stop_sending_button_updates(self):
        self._send_button_events = False
        logger.info("Stopped button updates")

    # As the Decent Scale sends all message types on the same cuuid, this is a
    # centralised handler to decipher the message type and act appropriately
    # (or broadcast an event for others to do so)
    def _create_message_handler(self) -> Callable:
        scale = self

        self._message_handler_created = True
        
        logger.debug("New message handler requested")

        async def message_handler(sender, data):
            nonlocal scale

            now = time.time()

            # Message type constants
            WEIGHT_STABLE    = b'\xce'
            WEIGHT_CHANGING  = b'\xca'
            DISPLAY_RESPONSE = b'\x0a'
            TIMER            = b'\x0c'
            TARE_RESPONSE    = b'\x0f'
            BUTTON_TAP       = b'\xaa'

            # BUTTON_TAP message constants - for readability later
            BUTTON_CIRCLE    = b'\x01'
            BUTTON_SQUARE    = b'\x02'
            SHORT_TAP        = b'\x01'
            LONG_PRESS       = b'\x02'

            # Byte 7 of the message is a checksum of the first 6 - ensure it
            # checks out
            if not self.check_serial_byte_xor(data):
                logger.warning(f"Invalid checksum in message {data} -  ignored")

            else:
                # Determine message type (stored in byte 2) and action

                # Both of these message types have the same format and
                # contents, as noted in the API documentation
                if (data[1:2] == WEIGHT_STABLE) or\
                   (data[1:2] == WEIGHT_CHANGING):
                    if not self._send_weight_events:
                        logger.debug("As weight updates are not requested, " +
                                     "ignoring weight message from scale")

                    else:
                        # Per API advice, ignoring the "change in weight" data
                        # as dodgy.
                        self._update_scale_time_estimator(now)

                        w = int.from_bytes(data[2:4],
                                           self._byte_order,
                                           signed=True) / 10.0

                        await scale.event_weight_update.publish(
                            ScaleWeightUpdate(arrival_time=now,
                                              scale_time=
                                    self._scale_time_from_latest_arrival(now),
                                              weight=w)
                            )

                        # Weight data just spam in the log if not changing
                        if data[1:2] == WEIGHT_CHANGING:
                            logger.debug(f"Got weight data of: {w}" +
                                         f"using bytes {data[2:4]}" +
                                         f"from message {data}")

                elif data[1:2] == BUTTON_TAP:
                    if not self._send_button_events:
                        logger.debug("As button updates are not requested, " +
                                     "ignoring button message from scale")

                    else:
                        # The Decent Scale sends byte 3 to indicate the button
                        # pressed.  It also sends byte 4 to indicate a short
                        # tap or long press.  For simplicity with the Scale
                        # class' standardised interface, these have been
                        # combined into a single 2 bit value:
                        # BUTTON_CIRCLE & SHORT_TAP  = \b00 = 0
                        # BUTTON_CIRCLE & LONG_PRESS = \b01 = 1
                        # BUTTON_SQUARE & SHORT_TAP  = \b10 = 2
                        # BUTTON_SQUARE & LONG_PRESS = \b11 = 3
                        button_enum = None
                        if data[2:3] == BUTTON_CIRCLE:
                            button_enum = 0
                        elif data[2:3] == BUTTON_SQUARE:
                            button_enum = 2
                        else:
                            logger.warning("Unknown button type of " +
                                           f"{data[2:3]} - ignoring")

                        if button_enum is not None:
                            if data[3:4] == LONG_PRESS:
                                button_enum += 1
                            elif data[3:4] != SHORT_TAP:
                                button_enum = None
                                logger.warning("Unknown button tap duration " +
                                               f"of {data[3:4]} - ignoring")

                        if button_enum is not None:
                            sbp = ScaleButtonPress(arrival_time=now,
                                                   button=button_enum)

                            logger.debug("Button press message received of " +
                                         f"type: {button_enum}")

                            await scale.event_button_press.publish(sbp)

                elif data[1:2] == TIMER:
                    # Not supported by pyDE1, nor relevant given much better
                    # quality sources of timing exist
                    logger.debug("Ignoring timer update from scale as scale " +
                                 "time updates not supported by pyDE1")

                elif data[1:2] == TARE_RESPONSE:
                    logger.debug("Received successful tare response from " +
                                 f"scale - {data}")
                    await scale._event_tare_response.publish(ScaleResponse(
                        arrival_time=now,
                        type=TARE_RESPONSE,
                        data=data[2:3]))

                elif data[1:2] == DISPLAY_RESPONSE:
                    logger.debug("Received successful display change " +
                                 f"response from scale - {data}")
                    await scale._event_display_response.publish(ScaleResponse(
                        arrival_time=now,
                        type=DISPLAY_RESPONSE,
                        data=data[3:5]))

                else:  # unknown
                    logger.warning(f"Unknown message from scale: {data[1:2]}" +
                                   ", taken from {data}")

        return message_handler

    # This is somewhat redundant for API v1.0 as the scale will self-tare
    # regardless of what the software says.  May still be valuable though, just
    # so that the dataset will show a tare command around the right time.  Will
    # also be important for API v1.1.  As such, retaining for now.
    async def _subscribe_button_press(self):
        scale = self

        logger.info("Starting button press handler")

        async def circle_button_tare(sbp: ScaleButtonPress) -> None:
            nonlocal scale
            if sbp.button == 0:
                await scale.tare()
                logger.debug("Tare requested via short tap of circle button" +
                             "on scale")
            else:
                logger.warning(f"Button {sbp.button} - Not implemented")

        # noinspection PyTypeChecker
        self._button_tare_subscriber_id =\
            await self._event_button_press.subscribe(circle_button_tare)


Scale.register_constructor(DecentScale, 'Decent Scale')
