#!/usr/bin/env sh

set -e

# Copyright © 2021 Jeff Kletsky. All Rights Reserved.
#
# License for this software, part of the pyDE1 package, is granted under
# GNU General Public License v3.0 only
# SPDX-License-Identifier: GPL-3.0-only

. "$(dirname $0)"/_config

if [ -z "$SUDO_USER" ] ; then
  >&2 echo "Script must be run with sudo"
elif [ "$SUDO_UID" =  0 ] ; then
  >&2 echo "Script must be run with sudo by a normal user"
fi

# Create the pyde1 user if they do not yet exist.

if getent passwd "$PYDE1_USER" ; then
  echo "User $PYDE1_USER already exists"
else
  echo "Creating user $PYDE1_USER"
  adduser --system --group "$PYDE1_USER"
fi
usermod -a -G bluetooth "$PYDE1_USER"
id "$PYDE1_USER"
