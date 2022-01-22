..
    Copyright © 2022 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

===========================
Quick Start on Raspberry Pi
===========================

--------
Overview
--------

Although pyDE1 can be used on most any, current Linux-based OS and
potentially macOS, the Raspberry Pi provides a compact, budget-friendly
platform for pyDE1 and the related services. This page describes some of the
options for hardware and outlines and links to the various steps generally
needed to bring up a ready-to-pull system.

--------
Hardware
--------

A multi-core Raspberry Pi is recommended. The ones generally available
at the start of 2022 include:

* Raspberry Pi 3B+
* Raspberry Pi Zero 2
* Raspberry Pi 4B

Any of these should be sufficient to run pyDE1, the web server, the MQTT server,
serve pages for a web-based UI, and ancillary programs, such as uploading to
Visualizer or steam-to-temperature.

Any of the distributors listed on the Raspberry Pi site are likely reputable
and less expensive than going through third-party sales, such as eBay.
If in the US, pishop.ca may be worth checking as they ship to the US
and seem to be restocked on a different schedule than pishop.us.

Accessories
===========

Often worth ordering with the Pi are any special adapters you might need
to connect a keyboard or display.

* 3B+ (standard HDMI, standard USB A)

* Pi Zero 2

  * Mini-HDMI to something you have
  * USB-OTG (micro B to A female)

* Pi 4B (standard USB A)

  * Micro-HDMI to something you have

The "official" Raspberry Pi cables and power supplies aren't a lot more than
the generic ones. They *might* be better quality.

The 3B+ and Zero 2 can be run off a good-quality, USB "phone" charger that can
reliably supply 2.4 A. The 4B needs a USB-C supply of at least 15 W capacity.

If the case you choose doesn't come with heat sinks, they're usually not very
expensive and hopefully won't bump up the shipping costs.

microSD Cards
=============

I usually buy my cards somewhere other than where I buy my hardware.
A while back, they introduced "A" ratings for microSD cards, for "Application"
(phone) use. Cameras tend to occasionally write and read big things,
where applications tend to have much smaller and more frequent reads and writes.
I'd suggest at least an A1 rating (in addition to Class, U, and V ratings).
Speed isn't too much of an issue, but longevity is, at least for me, worth
a couple extra dollars. A 32 GB card should be plenty. 64 GB cards are
probably not much more expensive.

Cases
=====

I've been using C4Labs cases for many years. I think they're some of the best
out there. They are laser-cut acrylic or wood, not the cheap moulded junk.
He's a small business in Washington State, US, and I see that he
has distribution through at least Pi Hut-UK. I believe they all include
heat sinks.

For the Pi Zero 2, I like the `Zebra Zero Heatsink Case`_ (get the Zero 2
version) or, if you want access to the pin header, the `Zebra Zero 2 Heatsink
and GPIO Access Case`_.

The Pi 3B+ I have is in a solid-top `Zebra Classic Case`_

For the Pi 4B I have, I went with the `Zebra Bagel Fan Case`_, which includes
a fan at that price. The fan is quiet enough on 3.3 V to *not* buy a Noctua,
from someone who trades out fans on just about everything. There are several
other options, but I trusted the advice I got that the fan was a good idea
for the power dissipation of the 4B.

.. _Zebra Zero Heatsink Case: https://www.c4labs.com/product/zero-heatsink-case-raspberry-pi-zero-w/

.. _Zebra Zero 2 Heatsink and GPIO Access Case: https://www.c4labs.com/product/zebra-zero-2-gpio-heatsink-case-raspberry-pi-zero-2/

.. _Zebra Classic Case: https://www.c4labs.com/product/zebra-classic-case-raspberry-pi-3-b-13-color-options-7-upgrades/

.. _Zebra Bagel Fan Case: https://www.c4labs.com/product/zebra-bagel-fan-case-raspberry-pi-4b-3b-3b-2b-and-b-color-options/

--------------------
Installation Outline
--------------------

This section outlines the installation steps described on other pages, either
here, or with the documentation for the UI or other software.

* :doc:`Raspberry Pi OS</raspberry_os>`

  * Download installer, install image, preconfigured for WiFi and ssh access
  * Boot image and update OS
  * Change from ``pi`` user to a name of your choice, secure ``sudo``
  * Add yourself to the ``bluetooth`` group
  * Install ``python3-venv`` and some utility packages
  * Potentially tweak WiFi for stability

* :doc:`Web Server</nginx>`, ``nginx``

  * Install using ``apt``
  * Configure for reverse-proxying of pyDE1
  * Configure for reverse-proxying of websockets
  * Configure for GUI
  * Potentially configure TLS certificates

* :doc:`MQTT Broker</mosquitto>`, ``mosquitto``

  * Install using ``apt``
  * Configure for MQTT (for applications) and websockets (for browser)
  * Potentially configure TLS certificates
  * Modify firewall to block off-host access to websockets
  * Select and configure passwords and access control lists
  * Configure logging (so it's more human-readable)

* :doc:`Install pyDE1 and Visualizer uploader</installing>` along with it

  * Script to create the ``pyde1`` user
  * Script to create the expected directories
  * Script to create and populate a Python virtual environment ("venv")
  * Script to move the config files into ``/usr/local/etc/pyde1/``
  * Edit the config files to suit (remember your user names and passwords)
  * Script to enable pyDE1 and Visualizer uploader at boot
  * Configure log rotation

* Install your choice of UIs

* Enjoy a coffee
