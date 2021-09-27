#!/bin/sh

# Copyright © 2021 Jeff Kletsky. All Rights Reserved.
#
# License for this software, part of the pyDE1 package, is granted under
# GNU General Public License v3.0 only
# SPDX-License-Identifier: GPL-3.0-only

# Scan the run-time directory for files suggesting bluetooth devices still open
# close if found and log (via stderr and systemd)

: "${SEARCH_DIR:=/var/lib/pyde1}"
: "${SUFFIX:=.btid}"

files=$(ls ${SEARCH_DIR}/*${SUFFIX} 2>/dev/null)

if [ -z "$files" ] ; then
  return
fi

for file in $files
do
  >&2 printf "Closing connection from %s\n" "$file"

  if [ $(wc -l "$file" | cut -d ' ' -f1) -gt 0 ] ; then
    >&2 printf "ERROR: Multi-line file %s not processed\n" "$file"
    continue
  fi

  id=$(grep -E '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$' "$file")
  if [ -z "$id" ] ; then
    >&2 printf "ERROR: No valid Bluetooth ID found in %s\n" "$file"
    continue
  fi

  if ( bluetoothctl info "$id" | grep -F 'Connected: yes' ) ; then
    >&2 bluetoothctl disconnect "$id" && >&2 rm -v "$file"
  else
    >&2 printf "%s did not match 'Connected: yes'" $id
    >&2 rm -v "$file"
  fi
done

exit 0





