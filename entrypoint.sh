#!/bin/bash

service dbus start
bluetoothd &

python ./examples/try_de1.py