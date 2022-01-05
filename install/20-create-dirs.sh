#!/usr/bin/sh -e

# Copyright © 2021 Jeff Kletsky. All Rights Reserved.
#
# License for this software, part of the pyDE1 package, is granted under
# GNU General Public License v3.0 only
# SPDX-License-Identifier: GPL-3.0-only

. "$(dirname $0)"/_config

echo "Creating target directories"

mkdir -p /var/log/pyde1
chown $PYDE1_USER /var/log/pyde1

mkdir -p /var/lib/pyde1
chown $PYDE1_USER /var/lib/pyde1

ls -ld /var/log/pyde1
ls -ld /var/lib/pyde1

