#!/usr/bin/env sh

set -e

# Copyright © 2021 Jeff Kletsky. All Rights Reserved.
#
# License for this software, part of the pyDE1 package, is granted under
# GNU General Public License v3.0 only
# SPDX-License-Identifier: GPL-3.0-only

. "$(dirname $0)"/_config

echo "Creating Python venv at $VENV_PATH"

if ! dpkg --get-selections | egrep '^python3-venv\s+install$' ; then
  apt install python3-venv
fi

mkdir -p $VENV_PATH

python -m venv $VENV_PATH

. $VENV_PATH/bin/activate

pip install -U pip
pip install -U setuptools
pip install pyDE1
pip list

# "Where is pyDE1?"
python -c \
  'import importlib.resources ; print(importlib.resources.files("pyDE1"))'

