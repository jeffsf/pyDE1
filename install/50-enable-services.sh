#!/usr/bin/sh -e

# Copyright © 2021 Jeff Kletsky. All Rights Reserved.
#
# License for this software, part of the pyDE1 package, is granted under
# GNU General Public License v3.0 only
# SPDX-License-Identifier: GPL-3.0-only

for service in /usr/local/etc/pyde1/pyde1.service \
           /usr/local/etc/pyde1/pyde1-visualizer.service ; do

  systemctl link -f $service
  systemctl daemon-reload
  service_name=$(basename $service)
  systemctl enable $service_name
  systemctl restart $service_name

done
