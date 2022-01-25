..
    Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=====================
Configuring mosquitto
=====================

--------
Overview
--------

``mosquitto`` is an MQTT broker. When used with the pyDE1 suite, it receives
requests to publish MQTT notifications from the pyDE1 core, as well as the
Visualizer uploader. Clients can subscribe to one or more of these and the
broker will send them to the client. These notifications are what can be used
to update a client in effectively real time.

MQTT needs care in configuration as there is no distinction between a publisher
and a subscriber. Any client, if allowed by the broker, can publish. This
includes connections over WebSockets.

The approach taken with this example configuration is to at least reduce the
exposure within reasonable bounds. For the coffee connoisseur, this is
"Starbucks-quality" security. Not completely unpalatable, accepted unknowingly
by millions, yet completely lacking in so many things. Using Unix domain
sockets for same-host connections would be preferable, but the "standard"
MQTT library, `paho, doesn't support them`_. So, *localhost* is has to be.
For simplicity, as these are same-host connections, TLS is not used.

.. warning::

    Security should not be taken lightly. Even when "only" exposed on the loopback
    interface, any service poses a vector for attack. If on an accessible
    network segment, and even if not, use of TLS is highly recommended, along
    with more secure authorization than the username/password supplied by MQTT.

.. _`paho, doesn't support them`: https://github.com/eclipse/paho.mqtt.c/issues/864

--------------------
Installing mosquitto
--------------------

.. code-block:: sh

  apt install mosquitto mosquitto-clients

``mosquitto-clients`` is optional. It provides the ``mosquitto_pub`` and
``mosquitto_sub`` utilities that are useful for debugging and monitoring.

-------------------------------
Example mosquitto Configuration
-------------------------------

The default ``/etc/mosquitto/mosquitto.conf`` includes a directive to read
configuration from ``/etc/mosquitto/conf.d/``.

As discussed in the overview, this example configuration does not use TLS
and, as such, is not suitable for use on anything but the loopback interface
("localhost") and then only on hosts where you are confident that the loopback
interface can't be monitored.

.. warning::

  It appears that a WebSocket listener can't be restricted
  to the loopback interface, exposing it on the network.

The (mis-)behavior seen at
https://www.eclipse.org/lists/mosquitto-dev/msg00799.html
still appears to be the current behavior at least as of 2.0.11

Listeners Without TLS
=====================

Without TLS, the configuration of listeners is straightforward.

The ports here are not not "set in stone" the way that HTTP
and HTTP-S are specified.

``conf.d/listeners.conf``

.. code-block:: sh

  listener 1883 localhost

  listener 1884
  protocol websockets


Listeners Adding TLS
====================

Here, port 8883 was selected for MQTT over TLS. The WebSocket listener is
reverse-proxied by ``nginx``, so it is not enabled here.

``conf.d/listeners.conf``

.. code-block:: sh

  listener 1883 localhost

  listener 8883
  cafile /etc/ssl/certs/ca-certificates.crt
  # For verifiable certs (e.g, Let's Encrypt)
  # certfile /etc/mosquitto/certs/fullchain.pem
  # For stand-alone, self-signed certs
  certfile /etc/mosquitto/certs/cert.pem
  # For all types of certs
  keyfile /etc/mosquitto/certs/privkey.pem
  tls_version tlsv1.3

  listener 1884
  protocol websockets

As previously noted, ``mosquitto`` needs to be able to read the private key
as the ``mosquitto`` user, not ``root``. This is somewhat ugly, as reading
as ``root`` then dropping privelege helps protect the key from compromise.
For now, we note and live with the risks. At least until I can find a better
approach, ``privkey.pem`` needs to be (only) ``mosquitto``-readable.

::

  $ sudo chown mosquitto:root /etc/mosquitto/certs/privkey.pem
  $ sudo chmod 600 /etc/mosquitto/certs/privkey.pem
  $ ls -l /etc/mosquitto/certs/privkey.pem
  -r-------- 1 mosquitto root 3272 Jan  4 15:19 /etc/mosquitto/certs/privkey.pem

Current versions of ``pyDE1`` allow configuration of TLS for MQTT
through the config files. For details of the parameters,
see paho's ``Client.set_tls()``.  With a verifiable certificate,
setting ``mqtt.TLS: true`` should be sufficient. With self-signed certificates,
``mqtt.TLS_CA_CERTS`` likely would also need to be set to the path to
the corresponding CA or public certificate in use.


Blocking Off-Host Access to WebSockets
======================================

As the listener for WebSockets is on all interfaces, it presents enough of a
security risk to block the port from off-host access. There are several
firewall tools for Linux, many of which are very outdated and now deprecated.
Here are some simple rules using ``nftables`` that should block access to
port 1884 from other hosts. For more information on ``nftables``,
see, for example,
https://wiki.nftables.org/wiki-nftables/index.php/Simple_rule_management

.. warning::

  This is not a complete firewall. It will need to be integrated with
  your existing firewall.

.. code-block:: sh

  nft add inet filter input iifname != 'lo' tcp dport 1884 drop

On a "fresh" Debian Bullseye system, the resulting ruleset may look something
like the following:

.. code-block:: sh

  $ sudo nft -a list ruleset
  table inet filter { # handle 1
      chain input { # handle 1
          type filter hook input priority filter; policy accept;
          iifname != "lo" tcp dport 1884 drop # handle 4
      }

      chain forward { # handle 2
          type filter hook forward priority filter; policy accept;
      }

      chain output { # handle 3
          type filter hook output priority filter; policy accept;
      }
  }

You may need to enable and start ``nftables.service`` if it is not yet running.
``systemctl status nftables.service`` will show if it is enabled and/or running.
The ``enable``, ``start``, ... actions require root privilege (``sudo``).
The default configuration file is ``/etc/nftables.conf``.


Access Control and Authorization
================================

As there is no inherent concept of a listen-only MQTT client, it is important
to restrict to which topics clients can publish, or you risk running an "open"
MQTT server.

``/etc/mosquitto/conf.d/auth.conf``

.. code-block:: sh

  # allow_anonymous false requires changing the JavaScript
  # to include username and password. Ideally, this could be
  # dynamically generated for some minor security.
  # For now, just allow anonymous read access.
  allow_anonymous true

  # include_dir dir
  #    [...] All files that end in '.conf' will be loaded
  # (so files not ending in .conf are "safe" here)

  password_file /etc/mosquitto/conf.d/passwords
  acl_file /etc/mosquitto/conf.d/acls

.. note::

  The user names and passwords you pick here will need to be
  edited into ``pyde1.conf`` and ``pyde1-visualizer.conf``,
  which will be installed later.


``/etc/mosquitto/conf.d/acls``

.. code-block::

  # Here it is assumed that the topic root is pyDE1

  # "The first set of topics are applied to anonymous clients,
  #  assuming allow_anonymous is true."
  topic read pyDE1/#

  # The main executable
  user pyde1
  topic readwrite pyDE1/#

  # The visualizer uploader
  user pyde1-visualizer
  topic read pyDE1/#
  topic write pyDE1/VisualizerUpload

``/etc/mosquitto/conf.d/passwords``

Create the passwords with ``mosquitto_passwd``. The first time you probably
need to add the ``-c`` (create new password file) option.

.. warning::

  Do *not* use the login password here.

  You do not need an OS-level user for these.

.. code-block:: sh

  mosquitto_passwd -c /etc/mosquitto/conf.d/passwords pyde1
  mosquitto_passwd /etc/mosquitto/conf.d/passwords pyde1-visualizer

These passwords and user names need to agree with those in ``pyde1.conf`` and
``pyde1-visualizer.conf``

Confirm that the file is readable by *mosquitto* but not writable by other
than *root*.

Logging
=======

``/etc/mosquitto/conf.d/logging.conf``

The change here is to use human-readable timestamps in the log files, rather
than Unix timestamps.

.. code-block::

  log_timestamp_format %Y-%m-%dT%H:%M:%S

.. note::

  Remember to ``sudo systemctl restart mosquitto.service`` to have the changes take effect.
