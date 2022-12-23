"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

New information on protocol and values based packet capture of
a Lunar 2021 and "acaia Coffee" iOS in Jan/Feb 2022 by Jeff Kletsky

---

Naming of some elements of MessageType and EventType after
https://github.com/ntoto/ACAIAScale_Arduino/blob/master/Scale.cpp
As such, these names might be considered as

Copyright (c) 2017 Nicolas Pouvesle

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# 
# LUNAR-E01E31 (Lunar 2021 on Firmware 1.00.001 or 1.00.005)
# 
# nRF Connect:
# ------------
# Connected at 13:16:19
# Last resp at 13:16:20
# Timed out at 13:16:26
# 
# Services:
# 49535343-C9D0-CC83-A44A-6FE238D06D33, 
#     49535343-FE7D-4AE5-8FA9-9FAFD205E455, 
#     and Device Information Services (180a)
# 
# Service 49535343-C9D0-CC83-A44A-6FE238D06D33
#     Char 49535343-ACA3-481C-91EC-D85E28A60318 write, notify
#     
# Service 49535343-FE7D-4AE5-8FA9-9FAFD205E455
#     Char 49535343-1E4D-4BD9-BA61-23C647249616 write, notify (WEIGHT)
#     Char 49535343-4C8A-39B3-2F49-511CFF073B7E write, write w/o resp, notify
#     Char 49535343-8841-43F4-A8D4-ECBE34729BB3 write, write w/o resp (COMMAND)
#     
# 2a23    System ID
# 2a24    Model Number String
# 2a25    Serial Number String
# 2a26    Firmware Revision String
# 2a27    Hardware Revision String
# 2a28    Software Revision String
# 2a29    Manufacturer Name String
# 2a2a    IEEE 11073-20601 Regulatory Certification Data List
#

# 2022-12-17 -- available firmware
#   Lunar 2.6.016           (AL006 in hand)
#   Lunar (2021) 1.0.009
#
# Seen on ACAIAL1
#
# 2a80  Age             Write w/o, notify
# 2a19  Battery level   Read, notify
# 2a50  PnP ID          Read -- 0x30-30-31-43-39-37
#
# 2a25  Serial number
# 2a26  Firmware rev
# 2a27  Hardware rev
# 2a28  Software rev
# 2a29  Manufacturer
#

import asyncio
import enum
import logging
import time
from typing import Optional, Union, Coroutine, Awaitable, NamedTuple

import bleak

import pyDE1
import pyDE1.event_manager
from pyDE1.scale.generic_scale import GenericScale, register_scale_class
from pyDE1.scale.events import ScaleWeightUpdate
from pyDE1.supervise import SupervisedTask

from pyDE1.config import config

logger = pyDE1.getLogger('Scale.Acaia')
logger_notify = logger.getChild('Notify')


class InteractionStyle (enum.Enum):
    CLASSIC = 'classic'
    LUNAR = 'lunar'


class CUUID (enum.Enum):
    # "CLASSIC"
    # '2a80' is an Assigned Number in "16-bit UUID Numbers Document", 2022-01-26
    # https://btprodspecificationrefs.blob.core.windows.net/assigned-values/16-bit%20UUID%20Numbers%20Document.pdf
    AGE     = '00002a80-0000-1000-8000-00805f9b34fb'
    # "LUNAR"
    COMMAND = '49535343-8841-43f4-a8d4-ecbe34729bb3'  # write, w/o resp
    WEIGHT  = '49535343-1e4d-4bd9-ba61-23c647249616'  # write, notify
    UNKNOWN = '49535343-4c8a-39b3-2f49-511cff073b7e'  # write, w/o resp, notify

    # These seem to be from https://www.microchip.com/en-us/product/BM70
    # rather than related to the Lunar (running v1.00.001 FW at the time)
    SYSTEM_ID       = '2a23'    # b'\x00\x00\x00\x00\x00\x00\x00\x00'
    MODEL_NUMBER    = '2a24'    # b'BM70'
    SERIAL_NUMBER   = '2a25'    # b'0000'
    FIRMWARE_REV    = '2a26'    # b'009010'
    HARDWARE_REV    = '2a27'    # b'5505 102_LESDK'
    SOFTWARE_REV    = '2a28'    # b'0000'
    MANUFACTURER    = '2a29'    # b'MCHP'
    # This is apparently related to medical devices, like glucose meters
    IEEE_11073_20601 = '2a2a'   # b'\x00\x00\x00\x00\x01\x00\x00\x00'

# When this message is delivered, it seems that the Lunar 2021
# isn't "properly" connected above the Bluetooth layer
# It seems that it will disconnect Bluetooth relatively quickly
# At this time (Feb, 2022), detection of this packet is used
# to preemptively disconnect and reconnect to the Acaia scale.

NOT_REALLY_CONNECTED = bytes.fromhex('efdd 0707 0219 0100 0501 2108')

# May also not be really connected if CUUID.COMMAND is not present


# Header byte pattern, may be multiple messages in single packet
# message[0] and message[1]
# This is intentionally bytes so .startswith() and .find() work
# TODO: Is bytes still needed or would bytearray work?

HEADER = b'\xef\xdd'


# message[2]
class MessageType (enum.IntEnum):
    SYSTEM      = 0x00
    TARE        = 0x04
    INFO        = 0x07
    STATUS      = 0x08
    IDENTIFY    = 0x0b
    EVENT       = 0x0c
    TIMER       = 0x0d

    REQUEST_02  = 0x02
    REQUEST_06  = 0x06
    CONFIG      = 0x0a


# message[3] is length in bytes,
# exclusive of three leading and two trailing bytes
# length includes itself
#
# message[3] can also be a sequence number
# for things like config, status requests, heartbeat, timer, (more?)


# TIMER request is sent with a sequence number
class TimerRequestType (enum.Enum):
    START   = b'\x00'
    RESET   = b'\x01'  # Appears to both stop and zero
    STOP    = b'\x02'


# CONFIG requests are sent with a sequence number
class ConfigType (enum.IntEnum):
    UNITS       = 0x00  # 0x05 oz, 0x02 grams; STATUS[1]
    AUTO_OFF    = 0x01  # 0x00 off, 0x01 5 min, 0x02 10 min,
                        # 0x03 20 min, 0x04 30 min, 0x05 60 min; STATUS[3]
    TOUCHPAD    = 0x02  # 0x78 120 seconds disabled; STATUS[4]
    UNKNOWN     = 0x03
    CAPACITY    = 0x04  # 0x00 1 kg, 0x01 2 kg; STATUS[7]
    BEEP        = 0x05  # 0x00 off, 0x01 on; STATUS[5]


class ConfigUnits (enum.IntEnum):
    OZ = 0x05
    G =  0x02


class ConfigAutoOff (enum.IntEnum):
    NONE   = 0x00
    MIN_5  = 0x01
    MIN_10 = 0x02
    MIN_20 = 0x03
    MIN_30 = 0x04
    MIN_60 = 0x05


class ConfigRange (enum.IntEnum):
    KG_1 = 0x00
    KG_2 = 0x01


class ConfigBeep (enum.IntEnum):
    OFF = 0x00
    ON  = 0x01


class Info (NamedTuple):
    battery: int
    units: ConfigUnits
    unk2: int
    auto_off: ConfigAutoOff
    unk4: int
    beep: ConfigBeep
    range: ConfigRange


# message[4]
class EventType (enum.IntEnum):
    WEIGHT      = 0x05
    # BATTERY     = 0x06
    TIMER       = 0x07
    KEY         = 0x08
    ACK         = 0x0b

    REPLY_06    = 0x06


# message[-2] is even-index checksum
# message[-1] is odd-index checksum
# Each checksum is the least-significant byte of the sum
# over the bytes of the payload (including its length byte)

def checksum(len_payload: Union[bytes, bytearray],
             is_request = False) -> bytearray:
    if not is_request and (len(len_payload)) != len_payload[0]:
        raise ValueError(
            "Inconsistent length byte in len_payload "
            f"{len_payload.hex(sep=' ', bytes_per_sep=-2)}")
    evens = 0
    odds = 0
    for idx in range(0, len(len_payload)):
        if (idx % 2):
            odds += len_payload[idx]
        else:
            evens += len_payload[idx]
    return bytearray((evens & 0xff, odds & 0xff))


def pack_message(message_type: MessageType,
                 payload: Union[bytes, bytearray]) -> bytearray:
    length_byte = 1 + len(payload)
    if length_byte > 255:
        raise ValueError("Unexpectedly long payload "
                         f"{payload.hex(sep=' ', bytes_per_sep=-2)}")
    packed = bytearray(HEADER)
    packed.extend((message_type.value, length_byte))
    packed.extend(payload)
    packed.extend(checksum(packed[3:]))
    return packed


def pack_request(message_type: MessageType,
                 sequence_number: int,
                 payload: Union[bytes, bytearray]) -> bytearray:
    if len(payload) > 2:
        raise ValueError("Unexpectedly long payload "
                         f"{payload.hex(sep=' ', bytes_per_sep=-2)}")
    packed = bytearray(HEADER)
    packed.extend((message_type.value, sequence_number))
    packed.extend(payload)
    packed.extend(checksum(packed[3:], is_request=True))
    return packed


def pack_config(setting_type: ConfigType,
                sequence_number: int,
                setting_enum_instance: Union[
                     ConfigUnits,
                     ConfigAutoOff,
                     ConfigRange,
                     ConfigBeep
                 ]) -> bytearray:
    # Why is this a tuple that is raising "unexpected type"?
    # Probably because it is two int values that aren't seen that way
    payload = bytes((setting_type.value, setting_enum_instance.value))
    return pack_request(MessageType.CONFIG, sequence_number, payload)


class FixedMessage (enum.Enum):
    """
    These messages are not time/situation varying
    and may not follow the `pack_message` format

    Gathered from iOS "acaia Coffee" app on 2022-01-31 and again 2022-12-18
    """
    IDENT   = bytes.fromhex('EFDD 0B2D 2D2D 2D2D 2D2D 2D2D 2D2D 2D2D 2D2D 683B')

    # Follows with
    #   Channel ID: 0x0004  Length: 0x0011 (17) [ 52 0D 00
    #   EF DD 0C 09 00 01 01 02 02 05 03 04 15 ... ]

    # App sends every 5 seconds
    UNKNOWN_1 = bytes.fromhex('EFDD 0200 0000')
    HEARTBEAT = bytes.fromhex('EFDD 0002 0002 00')
    STATUS_REQUEST = bytes.fromhex('EFDD 0600 0000')  # seq can increment

    # Both UNKNOWN_1 and STATUS_REQUEST seem to increment a sequence numbber
    # after every command send
    # ... 0204 0400 and 0604 0400
    # ... 0205 0500 and 0605 0500
    # wraps at ff back to 00

    TARE        = bytes.fromhex('EFDD 0400 0000')

# Messages that don't conform to the MessageType|length format
# The 'efdd 200c 0c00' pattern seems to occur when reconnecting
# to the scale after it has been off a while.

NONSTANDARD_MESSAGES = (
    bytes.fromhex('efdd 2008 0800'),    # Power up?
    bytes.fromhex('efdd 200c 0c00'),    # Power down?
    bytes.fromhex('efdd 200a 0a00'),    # ?
)


def hex_logstr(message: Union[bytes, bytearray]) -> str:
    """
    Utility to render as groups of 4 nibbles, from the left
    """
    return message.hex(bytes_per_sep=-2, sep=' ')


class TimestampedData (NamedTuple):
    timestamp: float
    data: Union[bytes, bytearray]

# This holds the common functionality, but is NOT registered
class AcaiaGeneric (GenericScale):

    # _supports_prefixes = None
    _requires_heartbeat = True
    _heartbeat_period = 5  # Seconds
    _style = InteractionStyle.CLASSIC

    def __init__(self):
        super(AcaiaGeneric, self).__init__()
        self._adopt_sync()

    def _adopt_sync(self):
        # This config override is for development only, will be deprecated
        # 8<
        if config.acaia.INTERACTION_STYLE is not None:
            self._style = InteractionStyle(config.acaia.INTERACTION_STYLE)
        if config.acaia.REQUIRES_HEARTBEAT is not None:
            self._requires_heartbeat = config.acaia.REQUIRES_HEARTBEAT
        if config.acaia.HEARTBEAT_PERIOD is not None:
            self._heartbeat_period = config.acaia.HEARTBEAT_PERIOD
        # >8

        self._nominal_period = 0.1  # seconds per sample
        self._minimum_tare_request_interval = 2.5 * self._nominal_period
        self._sensor_lag = 0.38  # seconds, including all transit delays
        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"

        self._info: Optional[Info] = None

        # logger = pyDE1.getLogger(self.__class__.__name__)
        # logger_notify = logger.getChild('notify')
        self._packet_buffer = bytearray()
        self._packet_buffer_lock = asyncio.Lock()

        self._heartbeat: Optional[SupervisedTask] = None
        self._control_lock = asyncio.Lock()

        self._setting_seq_number = 0
        self._timer_seq_number = 0

        if self._style == InteractionStyle.CLASSIC:
            self._command_cuuid = CUUID.AGE
            self._notify_cuuid = CUUID.AGE
            self._notify_lock = self._control_lock
        else:
            self._command_cuuid = CUUID.COMMAND
            self._notify_cuuid = CUUID.WEIGHT
            self._notify_lock = asyncio.Lock()

    async def _adopt_class(self):
        self._adopt_sync()

    async def _leave_class(self):
        try:
            self._heartbeat.cancel()
        except AttributeError as e:
            logger.error(f"Unable to cancel Acaia heartbeat: {e}")
        for attr in (
            # Class attributes, not instance attributes
            # '_style',
            # '_requires_heartbeat',
            # '_heartbeat_period',
            '_info',
            '_packet_buffer',
            '_packet_buffer_lock',
            '_heartbeat',
            '_control_lock',
            '_setting_seq_number',
            '_timer_seq_number',
            '_command_cuuid',
            '_notify_cuuid',
            '_notify_lock',
        ):
            delattr(self, attr)

    async def _initialize_after_connection(self, hold_ready=False):
        await super(AcaiaGeneric, self)._initialize_after_connection(
            hold_ready=True)
        # Check here to confirm "really connected"
        # Another symptom is NOT_REALLY_CONNECTED received as a packet
        if not self._bleak_client.services.get_characteristic(
                self._command_cuuid.value):
            logger.warning(
                f"CUUID {self._command_cuuid.value} not found, "
                "disconnecting for reconnect")
            logger.info(
                ', '.join(map(lambda c: c.uuid.removesuffix(
                    '-0000-1000-8000-00805f9b34fb'),
                    list(self._bleak_client.services.characteristics.values()))))
            await self.disconnect(for_reconnect=True)
            return

        await self._send_ident()
        await self._send_config()
        if self._requires_heartbeat:
            self._heartbeat = SupervisedTask(
                self._send_heartbeat,
            )
            self._heartbeat.work.name=f"{self.__class__.__name__}_Heartbeat"

        self._notify_ready()

    async def _send_packet(self, packet: Union[bytes, bytearray]):
        async with self._control_lock:
            await self._bleak_client.write_gatt_char(
                self._command_cuuid.value, packet)

    async def _send_ident(self):
        await self._send_packet(FixedMessage.IDENT.value)

    async def _send_config(self):
        await self._send_packet(
            pack_message(MessageType.EVENT,
                         bytes.fromhex('0001 0102 0205 0304')))

    async def _send_heartbeat(self):
        more = ''
        while self.is_connected:  # would error if not connected
            try:
                await self._send_packet(FixedMessage.HEARTBEAT.value)
            except bleak.exc.BleakError as e:
                more = e
                break
            await asyncio.sleep(self._heartbeat_period)
        logger.info(f"Discontinuing heartbeat {more}")

    async def start_sending_weight_updates(self):
        async with self._notify_lock:
            await self._bleak_client.start_notify(
                self._notify_cuuid.value,
                self._notification_handler)

    async def stop_sending_weight_updates(self):
        async with self._notify_lock:
            await self._bleak_client.stop_notify(self._notify_cuuid.value)

    async def disconnect(self, for_reconnect=False):
        if self._heartbeat:
            await self._heartbeat.work.cancel()
            self._heartbeat = None
        await super(AcaiaGeneric, self).disconnect(for_reconnect=for_reconnect)

    async def display_on(self):
        pass

    async def display_off(self):
        pass

    async def _tare_internal(self):
        await self._send_packet(FixedMessage.TARE.value)

    # ACKs on timer events appear to reflect the sequence number
    # efdd 0c04 0b01 2105 2c
    #             || sequence number
    #                || 21 - stop, 01 - start, 41 - reset
    # Sometimes longer
    # efdd 0c0b 0b00 0105 2d00 0000 0202 123b
    # efdd 0c0b 0b01 2105 2e00 0000 0202 135c
    # efdd 0c0b 0b02 0105 3400 0000 0202 1442
    # efdd 0c0b 0b03 4105 3500 0000 0202 1583
    # efdd 0c0b 0b04 0105 3700 0000 0202 1645
    # efdd 0c0b 0b05 2105 3600 0000 0202 1764
    # efdd 0c0b 0b06 4105 3800 0000 0202 1886
    # efdd 0c0b 0b07 4105 3500 0000 0202 1983
    # efdd 0c0b 0b08 0105 3100 0000 0202 1a3f
    # efdd 0c0b 0b09 4105 2200 0000 0202 1b70

    # TIMER event -  efdd 0c05 0700 0502 070c
    #                             0:05?

    async def timer_start(self):
        seq = self._timer_seq_number
        self._timer_seq_number = (self._timer_seq_number + 1) & 0xff
        await self._send_packet(
            pack_request(MessageType.TIMER, seq, TimerRequestType.START.value))

    async def timer_stop(self):
        seq = self._timer_seq_number
        self._timer_seq_number = (self._timer_seq_number + 1) & 0xff
        await self._send_packet(
            pack_request(MessageType.TIMER, seq, TimerRequestType.STOP.value))

    async def timer_reset(self):
        seq = self._timer_seq_number
        self._timer_seq_number = (self._timer_seq_number + 1) & 0xff
        await self._send_packet(
            pack_request(MessageType.TIMER, seq, TimerRequestType.RESET.value))

    async def set_grams(self):
        seq = self._setting_seq_number
        self._setting_seq_number = (self._setting_seq_number + 1) & 0xff
        await self._send_packet(pack_config(ConfigType.UNITS,
                                            seq,
                                            ConfigUnits.G))

    async def set_ounces(self):
        seq = self._setting_seq_number
        self._setting_seq_number = (self._setting_seq_number + 1) & 0xff
        await self._send_packet(pack_config(ConfigType.UNITS,
                                            seq,
                                            ConfigUnits.OZ))

    async def set_beep(self, audible: bool):
        seq = self._setting_seq_number
        self._setting_seq_number = (self._setting_seq_number + 1) & 0xff
        await self._send_packet(pack_config(ConfigType.BEEP,
                                            seq,
                                            ConfigBeep.ON if audible else
                                                ConfigBeep.OFF))

    async def _notification_handler(self, sender: int, data: bytearray):
        """Callback for arriving BLE packets"""
        tsd = TimestampedData(timestamp=time.time(), data=data)
        async with self._packet_buffer_lock:
            # TODO: Watchdog this
            await self._process_data_under_lock(tsd)

    async def _process_data_under_lock(self, tsd: TimestampedData):
        """
        With self._packet_buffer_lock in hand...

        Messages can be split across multiple packets, as well as
        multiple messages arriving in a single packet.

        This passes single, "complete" messages to process_message()

        Seen with Lunar and perhaps not with Lunar 2001
            Scale.Acaia: Waiting for more bytes, 3 < 5 bytes ef:dd:0c
        """
        self._packet_buffer.extend(tsd.data)

        while (lpb := len(self._packet_buffer)):

            if lpb < 5:
                break

            # Check for the troublesome 'efdd 2008 0800' 'efdd ...'
            # for nsm in NONSTANDARD_MESSAGES:
            #     if self._packet_buffer.startswith(nsm):
            #         self._process_message(nsm)
            #         self._packet_buffer \
            #             = self._packet_buffer[len(nsm):]
            #         break

            if self._packet_buffer.startswith(b'\xef\xdd\x20'):
                await self._process_message(self._packet_buffer[0:6])
                self._packet_buffer = self._packet_buffer[6:]
                continue

            idx = self._packet_buffer.find(HEADER)
            if idx == 0:  # HEADER at start of buffer
                try:
                    len_byte = self._packet_buffer[3]
                except IndexError:
                    logger.debug(
                        f"Waiting for more bytes, no length byte yet")
                    break
                if lpb >= (loa := len_byte + 5):
                    if lpb > 26:  # 26 seen with ACK and TIMER
                        logger.warning(
                            f"Packet buffer getting long, at bytes: {lpb}")
                    await self._process_message(self._packet_buffer[0:loa],
                                                timestamp=tsd.timestamp)
                    self._packet_buffer = self._packet_buffer[loa:]
                else:
                    logger.debug(
                        f"Waiting for {loa - lpb} more bytes")
                    break
            else:
                if idx == -1:
                    if lpb == 1 \
                            and self._packet_buffer[0] == HEADER[0]:
                        logger.info(
                            "Packet buffer is just first HEADER byte")
                        break
                    if lpb >= 2:
                        discarded = self._packet_buffer
                        self._packet_buffer = bytearray()
                else:
                    discarded = self._packet_buffer[0:idx]
                    self._packet_buffer \
                        = self._packet_buffer[idx:]
                logger.warning(
                    "Packet buffer does not start with header, discarding "
                    + hex_logstr(discarded))



# Sometimes the Lunar connects from a Bluetooth perspective
# but doesn't respond as one would expect. One symptom of this
# is when the needed CUUID is missing, another is when
# 'efdd 0707 0219 0100 0501 2108' is received as a packet.
#
# Rather than wait for the Lunar to drop the connection from its end,
# drop from this side and initiate a reconnection.

# TODO: Think through this more carefully
#           Should a disconnect be called if already reconnecting?
#           When should the _reconnect_task be cleared?

    async def _process_message(self, message: Union[bytearray, bytes],
                               timestamp: Optional[float] = None):
        if not timestamp:
            timestamp = time.time()

        if message == NOT_REALLY_CONNECTED:
            logger.error("NOT REALLY CONNECTED packet seen")
            # "NOT REALLY CONNECTED packet seen, disconnecting to reconnect")
            # Strange, sometimes this continues without issue. Watch it
            # await self.disconnect(for_reconnect=True)

        if message == b'\xef\xdd\x20\x08\x08\x00':
            logger_notify.info("Acaia 0x2008 = power up?")
            return
        elif message == b'\xef\xdd\x20\x0a\x0a\x00':
            logger_notify.info("Acaia 0x200a = power down?")
            return
        elif message == b'\xef\xdd\x20\x0c\x0c\x00':
            logger_notify.info("Acaia 0x200c = power down?")
            return

        try:
            length_byte = message[3]
            expected_length = 3 + length_byte + 2
            if len(message) != expected_length:
                logger_notify.error(
                    f"Expected {expected_length} packet, "
                    f"got {len(message)} bytes: {hex_logstr(message)}")
        except IndexError:
            logger_notify.error(
                f"Very short packet, "
                f"got {len(message)} bytes: {hex_logstr(message)}")
            return

        if len(message) < 7:
            logger_notify.error(f"Short packet: {hex_logstr(message)}")
            return

        try:
            message_type = MessageType(message[2])
        except ValueError as e:
            logger_notify.error(
                f"0x{message[2]:02x} {e}: {hex_logstr(message)}")
            return

        if message_type == MessageType.EVENT:
            try:
                event_type = EventType(message[4])
            except ValueError as e:
                logger_notify.error(f"{e}: {hex_logstr(message)}")
                return
        else:
            event_type = None  # Not really needed, but keeps pyCharm happy

        #

        if message_type == MessageType.EVENT:

            if event_type == EventType.WEIGHT:

                # Common for all three variants

                # 6 bytes or more bytes before checksum
                mantissa = message[5] + message[6] * 256 + message[7] * 65536
                scale_by = 10 ** message[9]  # Production do this faster
                if message[10] & 0x02:
                    sign = -1
                else:
                    sign = 1
                weight = sign * mantissa / scale_by

                if (message[10] & 0x01):  # Weight unsettled if & 0x01
                    other = '~'
                else:
                    other = ''

                if length_byte == 0x08:
                    pass

                elif length_byte == 0x0a:
                    # Seen on Lunar but not Lunar 2021
                    unknown11 = message[11]
                    battery = message[12]
                    unknown13 = message[13]
                    other = f"{other} {battery}% {unknown11}[11] {unknown13}[13]"
                    logger_notify.debug(
                        f"0x0a length: {weight}g {other} {hex_logstr(message)}")

                elif length_byte == 0x0c:
                    # it is a status, weight notification, "long version"

                    unk11 = message[11]
                    minutes = message[12]
                    seconds = message[13]
                    tenths = message[14]  # Seemingly, though why "2" at start?

                    other = f"{other} {unk11} {minutes}:{seconds:02.0f},{tenths:01.0f}"

                elif length_byte == 0x0e:
                    # it is a status, weight notification, "longer version"

                    unk11 = message[11]
                    battery = message[12]  # Guessing, 0x64 at 100%
                    unknown = message[13]
                    minutes = message[14]
                    seconds = message[15]
                    tenths = message[16]  # Seemingly, though why "2" at start?

                    other = f"{other} {unknown} " \
                            f"{minutes}:{seconds:02.0f},{tenths:01.0f} " \
                            f"- {unk11} {battery}%"

                else:
                    logger_notify.error(
                        f"{message_type.name}, {event_type.name} "
                        f"0x{len(message) - 4:02x} bytes unexpected: "
                        f"{hex_logstr(message)}")

                # asyncio.get_running_loop().create_task(
                await self.event_weight_update.publish(
                        ScaleWeightUpdate(
                            arrival_time=timestamp,
                            scale_time=self._scale_time_from_latest_arrival(
                                timestamp),
                            weight=weight
                        ))
                # )

            elif event_type == EventType.REPLY_06:
                logger_notify.info(
                    f"{message_type.name}, {event_type.name}: "
                    f"{hex_logstr(message)}")

            elif event_type == EventType.TIMER:
                logger_notify.info(
                    f"{message_type.name}, {event_type.name}: "
                    f"{hex_logstr(message)}")

            elif event_type == EventType.KEY:
                logger_notify.info(
                    f"{message_type.name}, {event_type.name}: "
                    f"{hex_logstr(message)}")

                # KEY: 0c: 0a 08 08 05 09 00 00 00 02 03 1d
                # KEY: 0c: 0a 08 08 05 14 00 00 00 02 01 28
                # KEY: 0c: 0a 08 08 05 15 00 00 00 02 03 29
                # KEY: 0c: 0a 08 08 05 16 00 00 00 02 03 2a
                # KEY: 0c: 0a 08 08 05 17 00 00 00 02 03 2b
                # KEY: 0c: 0a 08 08 05 18 00 00 00 02 03 2c
                # KEY: 0c: 0a 08 08 05 19 00 00 00 02 03 2d
                # KEY: 0c: 0a 08 09 05 14 00 00 00 02 03 29
                # KEY: 0c: 0a 08 09 05 17 00 00 00 02 03 2c
                # KEY: 0c: 0a 08 09 05 17 00 00 00 02 03 2c
                # KEY: 0c: 0a 08 09 05 18 00 00 00 02 03 2d
                # KEY: 0c: 0a 08 09 05 39 00 00 00 02 03 4e
                # KEY: 0c: 0a 08 0a 05 00 00 00 00 02 01 16
                # KEY: 0c: 0a 08 0a 05 12 00 00 00 02 01 28
                # KEY: 0c: 0e 08 08 05 17 00 00 00 02 03 07
                # KEY: 0c: 0e 08 08 05 18 00 00 00 02 03 07
                # KEY: 0c: 0e 08 09 05 17 00 00 00 02 03 07
                # KEY: 0c: 0e 08 09 05 17 00 00 00 02 03 07

            elif event_type == EventType.ACK:
                logger_notify.info(
                    f"{message_type.name}, {event_type.name}: "
                    f"{hex_logstr(message)}")

        elif message_type == MessageType.TARE:
            logger_notify.info(
                f"{message_type.name}: {hex_logstr(message)}")

        elif message_type == MessageType.INFO:
            # Not connected? WARNING Notify: INFO: 07: 07 02 19 01 00 01
            logger_notify.info(
                f"{message_type.name}: {hex_logstr(message)}")

        # Clues to status-message byte assignments from
        # https://github.com/oscar-b/scales/blob/master/src/acaia/scale.ts#L160
        elif message_type == MessageType.STATUS:
            payload = message[4:-2]
            battery = payload[0]
            try:
                units = ConfigUnits(payload[1])
            except ValueError as e:
                logger.error(f"In processing STATUS, {e}")
                units = '?'
            unk2 = payload[2]
            try:
                auto_off = ConfigAutoOff(payload[3])
            except ValueError as e:
                logger.error(f"In processing STATUS, {e}")
                auto_off = '?'
            unk4 = payload[4]
            try:
                beep = ConfigBeep(payload[5])
            except ValueError as e:
                logger.error(f"In processing STATUS, {e}")
                beep = '?'
            try:
                range = ConfigRange(payload[7])
            except ValueError as e:
                logger.error(f"In processing STATUS, {e}")
                range = '?'

            level = logging.INFO
            try:
                self._info = Info(
                    battery=battery,
                    units=units,
                    unk2=unk2,
                    auto_off=auto_off,
                    unk4=unk4,
                    beep=beep,
                    range=ConfigRange(range),
                )
            except ValueError as e:
                level = logging.INFO
                logger_notify.error(f"Error saving info data {e}")

            if battery > 100:
                level = logging.ERROR
            logger_notify.log(level,
                              "{}: {}% {} ({}) {} ({}) {} {}".format(
                                  message_type.name,
                                  battery,
                                  units.name,
                                  unk2,
                                  auto_off.name,
                                  unk4,
                                  beep.name,
                                  range.name,
                              ))

        elif message_type == MessageType.IDENTIFY:
            logger_notify.info(
                f"{message_type.name}: {hex_logstr(message)}")

        elif message_type == MessageType.TIMER:
            logger_notify.info(
                f"{message_type.name}: {hex_logstr(message)}")

        else:
            logger_notify.warning(
                f"Unrecognized message type: {hex_logstr(message)}")


# Register later to not conflict with ACAIAL1
@register_scale_class
class AcaiaAcaia (AcaiaGeneric):
    _supports_prefixes = ['ACAIA', 'ACAIAL1']
    _requires_heartbeat = False
    _style = InteractionStyle.CLASSIC


@register_scale_class
class AcaiaLunar(AcaiaGeneric):
    # Original Lunar seems to be CLASSIC
    _supports_prefixes = ['LUNAR']
    _requires_heartbeat = False
    _style = InteractionStyle.LUNAR

    def __init__(self):
        super(AcaiaLunar, self).__init__()
        # Seems like same speed as Skale II
        # when Lunar on "fast" filtering (default)
        self._sensor_lag = 0.38


@register_scale_class
class AcaiaProch (AcaiaGeneric):
    _supports_prefixes = ['PROCH']
    _requires_heartbeat = False
    _style = InteractionStyle.CLASSIC


@register_scale_class
class AcaiaPearlS (AcaiaGeneric):
    _supports_prefixes = ['PEARLS']
    _requires_heartbeat = False
    _style = InteractionStyle.LUNAR


@register_scale_class
class AcaiaPyxis (AcaiaGeneric):
    _supports_prefixes = ['PYXIS']
    _requires_heartbeat = False
    _style = InteractionStyle.LUNAR
