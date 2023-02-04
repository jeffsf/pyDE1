..
    Copyright © 2022-2023 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=============================
Backing Up the pyDE1 Database
=============================

------------
When and Why
------------

Backup strategies are always a subject of debate. If you're reading this,
I'm assuming you have already made some decision around your strategy.
This page discusses some of the options for database compression as well as
some hints about how to automate backups.

Even if you aren't scheduling periodic backups, when a schema update
is automatically performed from schema 2 or later, the database is backed up.
This backup is in the same folder as the "live" database. It may be
deleted when deemed appropriate.

-------------
Manual Backup
-------------

A manual backup of the pyDE1 database is possible using ``sqlite3`` commands.
As with any connection to the database, it should be done using the user
that owns the database, ``pyde1`` by default.

In an interactive session, one way to accomplish this is with

.. code-block:: sh

  sudo -u pyde1 sqlite3 /var/lib/pyde1/pyde1.sqlite3

The ``backup`` command can be executed from the prompt

.. code-block::

  sqlite> .help backup
  .backup ?DB? FILE        Backup DB (default "main") to FILE
       --append            Use the appendvfs
       --async             Write to FILE without journal and fsync()

-------------------
Compression Options
-------------------

The pyDE1 database is highly compressible. Selection of a compression tool
will depend on what has been installed on the system and the value of the
time vs. compression (disk space) tradeoff. Most Linux-based systems already
have ``gzip`` installed. It is a reasonable compressor in terms of speed and
ratio. Mainly as it is already installed, it is the default for the *post-facto*
compression of backups made during the schema-upgrade process.

Here are some example compression times and results. They were tested on
a Raspberry Pi 3B+ with a 64 GB microSD, probably an upper-grade SanDisk.
The database has 3196 rows in the ``sequence`` table.
Uncompressed it is 511.5 MB. Default compression was used for each program,
unless noted in the table. Time is "real" from the ``time`` utility.

.. list-table::

  * - Program
    - Time
    - Compressed
    - Fraction

  * - ``lz4``
    - 0:15
    - 143.1 MB
    - 28.0 %

  * - ``zstd -1``
    - 0:23
    - 101.2 MB
    - 19.8 %

  * - ``zstd``
    - 0:43
    - 100.2 MB
    - 19.6 %

  * - ``gzip``
    - 1:26
    - 98.6 MB
    - 19.3 %

  * - ``zstd -10``
    - 1:59
    - 86.8 MB
    - 17.0 %

  * - ``zstd -19``
    - 32:36
    - 76.6 MB
    - 15.0 %

  * - ``xz``
    - 15:54
    - 65.6 MB
    - 12.8 %

For scheduled backups, ``xz`` at the default compression level provides
the greatest disk-space savings of those tested. It may be "too slow"
even for overnight runs with very large databases.

Compression speed seems significantly faster on the Raspberry Pi 4,
with xz compression taking about half the time (7:24).

-----------------
Scheduled Backups
-----------------

As pyDE1 configures its database to be multi-user, it is possible to schedule
backups with standard OS tools, such as ``cron``. One approach is to use
a script that performs the backup to a unique name and then compresses it
when complete.

.. code-block:: sh

  #!/bin/sh

  filename=$(date +'/home/pyde1/db_backup/pyde1.%Y-%m-%d_%H%M.sqlite3')
  sqlite3 /var/lib/pyde1/pyde1.sqlite3 ".backup $filename"
  xz $filename

and then scheduling that script for execution by ``pyde1``.

One way to do this is to edit the ``crontab`` for the ``pyde1`` user.
Do not run as ``root`` as doing so may cause database files
to be owned by ``root``, preventing access by ``pyde1``.

.. code-block:: sh

  sudo -u pyde1 crontab -e
