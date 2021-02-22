"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import logging
from struct import unpack

import zlib
import binascii

# typedef struct {
#   U32 CheckSum;    // The checksum of the rest of the encrypted image. Includes "CheckSums" + "Data" fields, not "Header"
#   U32 BoardMarker; // 0xDE100001
#   U32 Version;     // The version of this image
#   U32 ByteCount;   // Number of bytes in image body, ignoring padding.
#   U32 CPUBytes;    // The first CPUBytes of the image are for the CPU. Remainder is for BLE.
#   U32 Unused;      // Blank spot for future extension. Always zero for now
#   U32 DCSum;       // Checksum of decrypted image
#   U8  IV[32];       // Initialization vector for the firmware
#   U32 HSum;        // Checksum of this header.
# } T_FirmwareHeader;


class FirmwareFile():

    def __init__(self, filename=None):
        self._filename = None
        self._checksum = None
        self._board_marker = None
        self._version = None
        self._byte_count = None
        self._cpu_bytes = None
        self._unused = None
        self._dc_sum = None
        self._initialization_vector = None
        self._header_checksum = None
        self._file_contents = None

        if filename is not None:
            self.filename = filename

    def _clear(self):
        self._checksum = None
        self._board_marker = None
        self._version = None
        self._byte_count = None
        self._cpu_bytes = None
        self._unknown = None
        self._dc_sum = None
        self._initialization_vector = None
        self._header_checksum = None

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, value):
        self._clear()
        self._filename = value

    @property
    def file_contents(self):
        if self._file_contents is None:
            self._load_from_file()
        return self._file_contents

    def _load_from_file(self):
        with open(self._filename, 'rb') as fh:
            # Header is
            #   7, 32-bit words (28 bytes)
            #   32-byte initialization vector
            #   1, 32-bit word of checksum (4 bytes)
            self._file_contents  = fh.read()
            print(f"File length: {len(self._file_contents)}")
            header = self._file_contents[0:64]
            (
                self._checksum,
                self._board_marker,
                self._version,
                self._byte_count,
                self._cpu_bytes,
                self._unknown,
                self._dc_sum,
                self._initialization_vector,
                self._header_checksum,
            ) = unpack('IIIIIII32sI', header)
            self._header = header
            # Not clear why
            print(f"binascii: {binascii.crc32(header[0:64]):08x}")
            print(f"zlib:     {zlib.crc32(header[0:64]):08x}")
            print(f"reported: {self._header_checksum:08x}")
            remainder = self._file_contents[64:]
            self._bytes_following = len(remainder)
            remainder_checksum = binascii.crc32(remainder)
            print()
            print(f"bcount: {self._byte_count}")
            print(f"length: {len(remainder)}")
            print(f"evaluated: {remainder_checksum:08x}")
            print(f"reported : {self._checksum:08x}")
            debug = True


if __name__ == '__main__':
    ff = FirmwareFile('../../bootfwupdate.dat')
    ff._load_from_file()

    print("done")

"""
Firmware update process:

11:38:29.743
Validate that the image is good, prior to writing (not being done now)

(what gets the DE1 into FW-update mode?? Is there any such thing?? GUI only??>)

11:38:54.329
Reboot DE1

11:39:38.806
Sleep the DE1
(Send fan temp of 60)

11:39:38.965
Send erase firmware: WI: 0, Erase: 1, Map: 1, FE: 0

11:39:48.828 - 12:30:02.530
Send firmware as write MMR 0x10 0x00 0000, 0010, 0020, ...
First packet is start of file itself (the header)

12:30:02.645
Enable map-request notifications

12:30:02.710
Use FirstError to determine if there are any errors
Iterate through them and "fix" them as needed

12:38:52.890
Reboot DE1
"""