#!/usr/bin/env bash

set -e
service dbus start
bluetoothd &
su $PYDE1_USER
pyde1-run
