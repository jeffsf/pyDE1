..
    Copyright © 2021 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=========================
Raspberry OS Install Tips
=========================

Raspberry OS images (formerly "Raspbian") can be obtained from the
`Raspberry Pi OS page`_. These are still 32-bit images, so should
run on all models. For the purposes of these hints, the "lite" image
is used. Those with a graphical desktop and with additional software
should configure in the same way.

.. _`Raspberry Pi OS page`: https://www.raspberrypi.com/software/operating-systems/
.. _`Raspberry Pi Imager`: https://www.raspberrypi.com/software/

In the past one would have had to jump through some hoops to enable SSH and WiFi
on first boot. Now, the `Raspberry Pi Imager`_ makes this a lot easier,
as well as "fixing" puzzling password problems because it came configured
for a GB keyboard and you then changed it to your own.

On macOS, you can run it directly from the mounted DMG file, without dragging
it to your Applications folder.

Open the hidden advanced-settings screen with cmd+shift+x for macOS or
ctrl+shift+x other OSes. You can now preconfigure networking with relative ease.

Make sure you set the WiFi country, or it may not be able to connect.

* Enable SSH

  * Use password authentication

    * Set password for 'pi' user: <enter your new password here>

* Configure wifi

  * SSID: <the name of your access point>
  * Password: <the password for your access point>
  * Wifi country <select your country code>

* Set locale settings

  * Time zone: <select yours>
  * Keyboard layout: <select yours>

Make other changes you might want, then click ``SAVE``

As I don't use the Raspberry Pi with a graphical desktop, the Lite image
is sufficient

  Operating System > Raspberry Pi OS (other) > Raspberry Pi OS Lite

As it will be writing to a "raw" device (the microSD), your OS may ask for
permissions to write to removable media or similar.

---------
Update OS
---------

Do this periodically

::

  pi@raspberrypi:~ $ sudo apt update
  pi@raspberrypi:~ $ sudo apt upgrade
  pi@raspberrypi:~ $ sudo reboot

---------------------------
Require a Password for sudo
---------------------------

Requiring a password probably makes things a bit more secure.

Confirm if pi (or your user) is in the *sudo* group first.

::

  pi@raspberrypi:~ $ id
  uid=1000(pi) gid=1000(pi) groups=1000(pi),4(adm),20(dialout),24(cdrom),27(sudo),29(audio),44(video),46(plugdev),60(games),100(users),105(input),109(netdev),997(gpio),998(i2c),999(spi)

If not, ``sudo usermod -a -G sudo pi`` and recheck.

Confirm that the *sudo* group is configured for access
with ``%sudo	ALL=(ALL:ALL) ALL``

::

  pi@raspberrypi:~ $ sudo fgrep sudo /etc/sudoers
  # This file MUST be edited with the 'visudo' command as root.
  # Please consider adding local content in /etc/sudoers.d/ instead of
  # See the man page for details on how to write a sudoers file.
  # Allow members of group sudo to execute any command
  %sudo	ALL=(ALL:ALL) ALL
  # See sudoers(5) for more information on "@include" directives:
  @includedir /etc/sudoers.d

Then cross your fingers and comment out the only line in
``sudo visudo /etc/sudoers.d/010_pi-nopasswd``

::

  # pi ALL=(ALL) NOPASSWD: ALL

-----------------------------
Change pi to Something Better
-----------------------------

I can make a security argument here for changing the "main" user name,
but I'll admit that convenience for me is a bigger driver.

There are four files that map user and group names to numbers and then the
name of the "home" directory in one of those. It's definitely possible to botch
this and get locked out. That's why I do it before there is much time invested.
Easier to re-image than to try juggling things.

.. warning::

  This needs to be done in one ``sudo`` session, as there are times when
  things are inconsistent and you may not be able to authenticate.

::

  pi@raspberrypi:~ $ sudo bash
  [sudo] password for pi:
  root@raspberrypi:/home/pi# cd /home
  root@raspberrypi:/home# ln -s pi jeff
  root@raspberrypi:/home# ls -l
  total 4
  lrwxrwxrwx 1 root root    2 Nov 18 20:51 jeff -> pi
  drwxr-xr-x 2 pi   pi   4096 Nov 18 21:09 pi

``vipw`` and change ``pi`` to ``jeff`` (or whatever) in the two places
in the line

::

  pi:x:1000:1000:,,,:/home/pi:/bin/bash

``vipw -s`` and change ``pi`` to ``jeff`` in the one place in the line

::

  pi:$5$a_bunch_of_apparently_random_characters:18930:0:99999:7:::

``vigr`` and change ``pi`` to ``jeff`` in lines like

::

  sudo:x:27:pi
  pi:x:1000:

(Don't change ``spi`` or ``gpio`` or similar)

``vigr -s`` and change ``pi`` to ``jeff`` similarly

Then complete things by renaming the home directory

::

  root@raspberrypi:/home# rm jeff
  root@raspberrypi:/home# mv pi jeff
  root@raspberrypi:/home# exit
  exit
  pi@raspberrypi:~ $ whoami
  jeff
  pi@raspberrypi:~ $ exit
  logout

Next time you log in, log in as your new user name (with the same password)

---------------------------------
Add Yourself to *bluetooth* Group
---------------------------------

::

  jeff@pi-walnut:~ $ sudo usermod -a -G bluetooth jeff

That way you can run ``bluetoothctl`` without elevated privilege.

--------------------
Install python3-venv
--------------------

The Python module to create virtual environments is not installed in the
base image. If ``$ dpkg --get-selections | fgrep python3`` does not list
``python3-venv``, install it with

::

  sudo apt install python3-venv

There's no "harm" in installing it if it is already there. ``apt`` would mark it
as "manually installed" if it was previously installed as a dependency.



----------------------------------
Utilities and Packages I Often Use
----------------------------------

::

  sudo apt install git ldnsutils locate sqlite3

``ldnsutils`` provides ``drill``, which I find useful to query DNS

``locate`` is a quick, file-name search across the entire system
that is helpful for *"Where are the .service files again?"* and the like.

``htop`` is already installed with the Raspberry OS image and is a more
fully featured monitoring tool than ``top`` without getting into huge
number of packages and that something like ``glances`` brings in.

---------------------------------------
Developers' Sidebar – Using pip and VCS
---------------------------------------

To be able to test out the sufficiency of the package and the installation
instructions, I didn't want to "publish" a package to PyPi that was either
incomplete or broken.

There is `VCS Support`_ for pip that alows an install to be done "on the fly"
from various VCS systems, or a file system.

.. _`VCS Support`: https://pip.pypa.io/en/latest/topics/vcs-support/

For my configuration, the following worked

::

  (test-pip-vcs) jeff@pi-walnut:~ $ pip install git+ssh://jeff@my.example.com/full/path/to/pyDE1.git@test#egg=pyDE1
  (test-pip-vcs) jeff@pi-walnut:~ $ pip list
  Package            Version
  ------------------ ---------
  aiosqlite          0.17.0
  bleak              0.13.0
  certifi            2021.10.8
  charset-normalizer 2.0.7
  dbus-next          0.2.3
  idna               3.3
  paho-mqtt          1.6.1
  pip                20.3.4
  pkg-resources      0.0.0
  pyDE1              0.9.1
  PyYAML             6.0
  requests           2.26.0
  setuptools         44.1.1
  typing-extensions  4.0.0
  urllib3            1.26.7

Other approaches are outlined at https://packaging.python.org/tutorials/installing-packages/#installing-from-a-local-src-tree
