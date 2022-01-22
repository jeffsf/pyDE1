..
    Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=============================
Installing and Enabling pyDE1
=============================

--------
Overview
--------

To enhance security, the ``pyDE1`` executables run as a dedicated user,
one with limited privilege. When possible, only read access is granted
to the files. None of the executables or configuration files should be
writable by *pyde1*. In this guide, they are set to *root* ownership.

.. warning::

  Accessing the database as any user other than *pyde1* may cause
  files to be written by that user, preventing access by *pyde1* [1]_

There are ``sh`` scripts provided that should make the process relatively
straightforward. As they are often run as *root* with ``sudo``, read them
and convince yourself that they are going to do what you expect, *before*
running them blindly.

Unless specifically noted, all scripts are to be run with *root*
privilege using ``sudo``.

.. [1] One way to access the database is with
   ``sudo -u pyde1 sqlite3 /var/lib/pyde1/pyde1.sqlite3``


------------
Walk-Through
------------

The scripts have been broken down into relatively small operations.
This allows them to be easily re-run should an error occur.

The scripts are *not* distributed in the ``pip`` package. They are present
in the `pyDE1 git repo`_, in the ``install/`` directory.
The repo can be cloned, or individual files downloaded. Make sure that
the ``_config`` file is in the same directory as the shell scripts.
Generally no changes need to be made to the ``_config`` file.

.. literalinclude:: ../install/_config

.. _`pyDE1 git repo`: https://github.com/jeffsf/pyDE1


10-create-user.sh
=================

This script will create the *pyde1* user if it does not exist
and give it access to the *bluetooth* group.

.. literalinclude:: ../install/10-create-user.sh
   :language: sh


20-create-dirs.sh
=================

This script will create the following directories and set their ownership
and permissions:

* ``/var/log/pyde1``
* ``/var/lib/pyde1``

.. literalinclude:: ../install/20-create-dirs.sh
   :language: sh


30-populate-venv
================

This creates a *root-owned*, Python virtual environment ("venv").
It then updates ``pip`` and ``setuptools`` and adds the ``pyDE1`` package
and its dependencies to the venv.

.. note::

   If you installed a non-default version of Python, such as 3.9 or 3.10 on an
   install of Raspberry Pi OS based on "Buster", you will need to explicitly
   reference that version when creating the venv.

   ``python -m venv $VENV_PATH`` would need to be edited to explicitly to
   refer to your chosen version. References after ``. $VENV_PATH/bin/activate``
   should not need modification, as that sets ``python`` to refer to the one
   in the venv.

.. literalinclude:: ../install/30-populate-venv.sh
   :language: sh


40-config-files.sh
==================

This copies the config files from the location where ``pip`` installed them
in the venv and into ``/usr/local/etc/pyde1``. It will make a timestamped
backup of any file that would be overwritten.

.. note::

  Some of the configuration files may contain sensitive credentials,
  such as MQTT and Visualizer usernames and passwords. These files
  are set to *root:pyde1* ownership with no other read access.

It also copies the ``pyde1.service`` and ``pyde1-visualizer.service`` files,
similarly making backups. These files are edited in place to adjust for
the specifics of the local install from the previous steps. The editor
(``sed``) backs up the original version with a ``.bak`` suffix.

Rather than run ``disconnect-btid.sh`` directly from the install, it is
copied to ``/usr/local/bin/pyde1-disconnect-btid.sh``. This script is run
by ``pyde1.service`` to help clean up any "stale" Bluetooth connections
related to a prior run that may have terminated ungracefully.

.. literalinclude:: ../install/40-config-files.sh
   :language: sh


Adjust Config Files to Suit
===========================

Examine the various config files ``/usr/local/etc/pyde1/*.conf`` and edit
as needed.

Changes that are commonly needed include:

In ``pyde1.conf``

* ``mqtt:``

    * ``USERNAME``
    * ``PASSWORD``

* ``de1:``

    * ``LINE_FREQUENCY``

In ``pyde1-visualizer.conf``

* ``mqtt:``

    * ``USERNAME``
    * ``PASSWORD``

* ``visualizer:``

    * ``USERNAME``
    * ``PASSWORD``

After completing the edits, ensure that they are readable by the *pyde1* group
and not by anyone else, other than *root*.

.. code-block::

  ls -l *.conf
  -rw-r----- 1 root pyde1 3555 Nov  3 18:18 pyde1.conf
  -rw-r----- 1 root pyde1 1789 Nov  3 18:18 pyde1-replay.conf
  -rw-r----- 1 root pyde1 2308 Nov  3 18:18 pyde1-visualizer.conf

If needed, the ownership and permissions can be corrected with

.. code-block:: sh

  sudo chown root:pyde1 *.conf
  sudo chmod 640 *.conf


50-enable-services.sh
=====================

This links the service definitions in ``/usr/local/etc/pyde1`` for the
``pyde1.service`` and the ``pyde1-visualizer.service`` to where ``systemd``
(the "startup manager" for Debian) knows about them, enables the services,
and restarts them. Unless they are explicitly disabled, they will start
on every boot.

Further information on service management can be found with

.. code-block:: sh

  man systemctl
  man journalctl

.. literalinclude:: ../install/50-enable-services.sh
   :language: sh


------------
Log Rotation
------------

The standard log-rotation utility on Debian is ``logrotate`` with
configuration in ``/etc/logrotate.d/``

One configuration that rotates daily, compresses,
and retains 60 days' of logs is

.. code-block::

    /var/log/pyde1/pyde1.log {
        daily
        missingok
        rotate 60
        compress
        delaycompress
        notifempty
        create
    }

    /var/log/pyde1/visualizer.log {
        daily
        missingok
        rotate 60
        compress
        delaycompress
        notifempty
        create
    }

Both the ``mosquitto`` and ``nginx`` packages install self-named config into
``/etc/logrotate.d/``
