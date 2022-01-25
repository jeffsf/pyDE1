==============
Updating pyDE1
==============

Updates to pyDE1 can be applied with ``pip`` when they become available.

The most-current, stable version can be checked at
https://pypi.org/project/pyDE1/

Unless you are working with the author on a new feature or resolving a bug,
the Stable releases are recommended.

-----------------------------------
Updating Your venv, Including pyDE1
-----------------------------------

To update the packages used by your virtual environment (venv), ``pip``
can check to see if any are outdated.

First, activate the venv so you are "inside" of it, rather than using the OS'
versions. Then you can check for outdated packages.

::

    jeff@pi-walnut:~ $ . ~pyde1/venv/pyde1/bin/activate
    (pyde1) jeff@pi-walnut:~ $ pip list --outdated
    Package Version Latest Type
    ------- ------- ------ -----
    bleak   0.14.1  0.14.2 wheel

Unfortunately, ``pip`` doesn't have an "update all" command, so I often end up
just going through the list, using the ``-U`` flag for updating.

::

  (pyde1) jeff@pi-walnut:~ $ pip install -U bleak
  Looking in indexes: https://pypi.org/simple, https://www.piwheels.org/simple
  Requirement already satisfied: bleak in /home/pyde1/venv/pyde1/lib/python3.9/site-packages (0.14.1)
  Collecting bleak
    Downloading https://www.piwheels.org/simple/bleak/bleak-0.14.2-py2.py3-none-any.whl (114 kB)
       |████████████████████████████████| 114 kB 190 kB/s
  Requirement already satisfied: dbus-next in /home/pyde1/venv/pyde1/lib/python3.9/site-packages (from bleak) (0.2.3)
  Installing collected packages: bleak
    Attempting uninstall: bleak
      Found existing installation: bleak 0.14.1
      Uninstalling bleak-0.14.1:
        Successfully uninstalled bleak-0.14.1
  Successfully installed bleak-0.14.2

If you're a command-line wrangler, you can figure out how to use ``xargs`` for
multiples, but I usually don't have enough to update to find my notes on that.

Restart Services
================

After updating, it is generally a good idea to restart the services that depend
on it and check that things are running smoothly. (You don't need to have
the venv activated for this.)

To exit the pager from the ``status`` command, use ``q``

.. code-block:: sh

  (pyde1) jeff@pi-walnut:~ $ sudo systemctl restart pyde1.service
  (pyde1) jeff@pi-walnut:~ $ sudo systemctl restart pyde1-visualizer.service
  (pyde1) jeff@pi-walnut:~ $ systemctl status pyde1.service
  ● pyde1.service - Main controller processes for pyDE1
     Loaded: loaded (/usr/local/etc/pyde1/pyde1.service; enabled; vendor preset: enabled)
     Active: active (running) since Fri 2022-01-28 09:11:46 PST; 20s ago
    Process: 30816 ExecStartPre=sh ${PYDE1_PATH}/services/runnable/disconnect-btid.sh (code=exited, status=0/SUCCESS)
   Main PID: 30818 (python3)
      Tasks: 26 (limit: 1597)
        CPU: 7.505s
     CGroup: /system.slice/pyde1.service
             ├─30818 /home/pyde1/venv/pyde1/bin/python3 /home/pyde1/venv/pyde1/lib/python3.9/site-packages/pyDE1/run.py
             ├─30819 /home/pyde1/venv/pyde1/bin/python3 -c from multiprocessing.resource_tracker import main;main(3)
             ├─30823 /home/pyde1/venv/pyde1/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=4, pi>
             ├─30824 /home/pyde1/venv/pyde1/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=4, pi>
             ├─30825 /home/pyde1/venv/pyde1/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=4, pi>
             ├─30826 /home/pyde1/venv/pyde1/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=4, pi>
             └─30827 /home/pyde1/venv/pyde1/bin/python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=4, pi>

  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,519 DEBUG [MainProcess] Config.YAML: Setting database.FILENAME
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,519 DEBUG [MainProcess] Config.YAML: Setting de1.LINE_FREQUENCY
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,520 DEBUG [MainProcess] Config.YAML: Setting de1.DEFAULT_AUTO_OFF_TIME
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,520 DEBUG [MainProcess] Config.YAML: Setting de1.STOP_AT_WEIGHT_ADJUST
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,521 INFO [MainProcess] Config.YAML: Config overrides loaded from /usr/lo>
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,700 INFO [MainProcess] root: Configured stderr_handler: <StreamHandler <>
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,701 INFO [MainProcess] root: Configured mqtt_handler: <PipeHandler (ERRO>
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,702 INFO [MainProcess] root: Configured logfile_handler: <WatchedFileHan>
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,704 INFO [MainProcess] root: Started <logging.handlers.QueueListener obj>
  Jan 28 09:11:47 pi-walnut pyde1[30818]: 2022-01-28 09:11:47,705 DEBUG [MainProcess] root: log_queue_listener handlers: (<StreamHandl>
  (pyde1) jeff@pi-walnut:~ $ systemctl status pyde1-visualizer.service
  ● pyde1-visualizer.service - Auto-upload to Visualizer
     Loaded: loaded (/usr/local/etc/pyde1/pyde1-visualizer.service; enabled; vendor preset: enabled)
     Active: active (running) since Fri 2022-01-28 09:11:57 PST; 52s ago
   Main PID: 30907 (python3)
      Tasks: 5 (limit: 1597)
        CPU: 1.633s
     CGroup: /system.slice/pyde1-visualizer.service
             └─30907 /home/pyde1/venv/pyde1/bin/python3 /home/pyde1/venv/pyde1/lib/python3.9/site-packages/pyDE1/services/runnable/p>

  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,798 DEBUG [MainProcess] Config.YAML: Setting logging.handlers>
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,799 DEBUG [MainProcess] Config.YAML: Setting logging.handlers>
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,799 DEBUG [MainProcess] Config.YAML: Setting logging.LOGGERS
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,799 DEBUG [MainProcess] Config.YAML: Setting mqtt.USERNAME
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,800 DEBUG [MainProcess] Config.YAML: Setting mqtt.PASSWORD
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,800 WARNING [MainProcess] Config.YAML: No entries found for d>
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,801 INFO [MainProcess] Config.YAML: Config overrides loaded f>
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,802 INFO [MainProcess] root: Configured stderr_handler: <Stre>
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,802 INFO [MainProcess] root: Configured mqtt_handler: <NullHa>
  Jan 28 09:11:58 pi-walnut pyde1-visualizer[30907]: 2022-01-28 09:11:58,803 INFO [MainProcess] root: Configured logfile_handler: <Wat>

Exiting the venv
================

Though usually it doesn't do any harm to stay in the venv, it can be exited with

::

  (pyde1) jeff@pi-walnut:~ $ deactivate
  jeff@pi-walnut:~ $

----------------------
Updating UI Components
----------------------

It is likely that UI components can be updated and they will be recognized
as soon as a request is made to the webserver. Check the documentation
for your UI on this.

Some components *might* need uWSGI (or other execution gateway) restarted.
This will depend on the configuration file. For example, KEpyDE1's config file
uses the ``touch-reload`` feature that automatically updates the code to be run
as soon as it is changed on disk.

::

  jeff@pi-walnut:~ $ fgrep touch-reload /etc/uwsgi-emperor/vassals/pyde1-db.ini
  touch-reload = dbget.py
  touch-reload = database_access.py
