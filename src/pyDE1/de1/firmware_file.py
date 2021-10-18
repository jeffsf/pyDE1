"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import binascii
import zlib
from struct import unpack

from pyDE1.exceptions import DE1ValueError


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

    def __init__(self, content=None, filename=None):
        if filename is not None and content is not None:
            raise ValueError(
                "Only one of 'content' and 'filename' can be specified"
            )
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
        self._content = None

        if filename is not None:
            self.filename = filename
            self._load_from_file()
        elif content is not None:
            self.content = content

    def _clear(self):
        self._checksum = None
        self._board_marker = None
        self._version = None
        self._byte_count = None
        self._cpu_bytes = None
        self._unused = None
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
    def content(self):
        if self._content is None and self.filename is not None:
            self._load_from_file()
        return self._content

    @content.setter
    def content(self, value):
        self._content = value
        self._populate_from_content()

    def _load_from_file(self):
        with open(self._filename, 'rb') as fh:
            self.content  = fh.read()

    def _populate_from_content(self):
        # See T_FirmwareHeader
        # Header is 64 bytes:
        #   7, 32-bit words (28 bytes)
        #   32-byte initialization vector
        #   1, 32-bit word of checksum (4 bytes)
        header = self._content[0:64]
        (
            self._checksum,     # Excludes "Header"
            self._board_marker, # 0xDE100001
            self._version,      # 4 byte int
            self._byte_count,   # Ignores padding
            self._cpu_bytes,    # Bytes to go to CPU, rest to BLE module
            self._unused,       # Reserved for later use
            self._dc_sum,       # Checksum of decrypted image
            self._initialization_vector,    # 32-byte initialization vector
            self._header_checksum,  # Checksum of header itself
        ) = unpack('IIIIIII32sI', header)
        self._header = header
        remainder = self._content[64:]
        self._bytes_following = len(remainder)
        if self._board_marker != 0xDE100001:
            raise DE1ValueError(
                "Firmware board marker not found, likely not valid firmware.")


if __name__ == '__main__':
    ff = FirmwareFile(filename='/home/jeff/fw/bootfwupdate.dat.1265')

    # Not clear why
    print()
    print(f"version:  {ff._version}")
    print(f"binascii: {binascii.crc32(ff._header[0:60]):08x}")
    print(f"zlib:     {zlib.crc32(ff._header[0:60]):08x}")
    print(f"reported: {ff._header_checksum:08x}")
    remainder = ff._content[64:]
    remainder_checksum = binascii.crc32(remainder)
    print()
    print(f"File:   {len(ff._content)}")
    print(f"length: {len(remainder)}")
    print(f"bcount: {ff._byte_count}, "
          f"diff: {len(remainder) - ff._byte_count}")
    print()
    print(f"evaluated: {remainder_checksum:08x}")
    print(f"reported : {ff._checksum:08x}")

    print()
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