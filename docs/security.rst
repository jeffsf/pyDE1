..
    Copyright © 2021 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

========
Security
========

-------
General
-------

You are responsible for your own security. This document does not warrant
any specific level of security, nor does it cover all possible security-related
issues. At best, it highlights some of the things you should be considering
for any software and OS.

Some general best practices:

* Keep your OS patched for all security issues, and update packages promptly.
* Run only the minimal set of programs and services
* Perform all operations with the lowest level of privilege for the task
* Blocking all and permitting selected is often stronger than permitting all
  and blocking known threats
* Maintain strong authorization credentials

----------------
TLS Certificates
----------------

TLS certificates, in the context of pyDE1 and allied services, generally provide
two functions, to confirm the identity of the service to a caller and to
set up an encrypted connection. What is now called TLS was previously known as
SSL and many sites and programs still refer to it as such.

.. warning::

  The private portion of these certificates should be considered as
  very sensitive data. Should they be used in an unauthorized setting,
  any device that "trusts" the certificate, directly or through its signature,
  would believe the imposter.

Verifiable Certificates Strongly Suggested
==========================================

If you have your own domain, using a recognized Certificate Authority (CA)
with a revocation list is the preferred way to obtain certificates.
Let's Encrypt is one service that can provide host-specific certificates
at no cost. These certificates can both be used to set up TLS connections,
as well as verify the identity of the host to which you're connecting.

Self-Signed Certificates
========================

.. note::

	I do not advocate use of self-signed certificates over verifiable certificates

If you do not have your own domain, many people use "self-signed" certificates
to set up TLS connections, but are dicey, at best, to verify identity. Most
modern browsers will raise a security warning with a self-signed certificate.
How you and those around you respond to those dialogs will impact the level
of risk involved with "accepting" the certificate. Most browsers will let you
examine the certificate before taking action. I strongly suggest doing so and
confirming that the certificate's details are what you expect. I can't comment
further on the best ways to handle these certificates. The risks likely vary by
OS and the level of trust you grant your system and apps for each certificate.

There are at least two ways of generating self-signed certificates. One is to
create your own, "trusted" CA, and have it sign certificates for various
uses. One can distribute the public key of the CA to all of your client devices
and "trust" that certificate. When one of your signed certificates is presented
by a service, the trust of the CA extends to the cert of the service.
For devices on which you haven't installed the CA public key, it will appear
as invalid, as there is no trust. Overviews of this approach can be found
in many places. One can be found at MariaDB_.

.. _MariaDB: https://mariadb.com/docs/security/encryption/in-transit/create-self-signed-certificates-keys-openssl/

.. _`mosquitto-tls man page`: https://mosquitto.org/man/mosquitto-tls-7.html

Stand-alone, self-signed certificates are another option. With these,
there is nothing to "trust" other than the certificate presented by the service
using it. They seem very popular with stand-alone IoT devices and networking
hardware. One source of a command line to generate a self-signed certificate is
adapted [1]_ from StackOverflow_

.. _StackOverflow: https://stackoverflow.com/questions/10175812/how-to-generate-a-self-signed-ssl-certificate-using-openssl

::

  openssl req -x509 -newkey rsa:4096 -keyout privkey.pem -out cert.pem -sha256 -days 365 -nodes

which will shortly prompt you for information that will be part of the
certificate, and generally visible in the "details" when examined in a browser.

*I suggest making them recognizable to yourself, as well as distinct for each
certificate you create.*

One suggestion is to set:

* *Organization Name* – your name
* *Organizational Unit Name* – something related to the service
* *Common Name* – The fully-qualified name of the host, or the IP address,
  if you're unable to set up local DNS
* *Email Address* – I often leave it blank

Many home routers will let you reserve an IP address for a specific host.
Often a hostname can be assigned for the DNS that the router provides.

Certificates and ``mosquitto``
==============================

Many services that employ sensitive data, such as TLS certificates, read that
data when they first start (as *root)* and then drop privilege before starting
the service. This allows the sensitive data to be readable only by *root*
and not readable by the unprivileged user that the service runs as.

For some reason, `current versions of mosquitto`_ no longer take this approach.
The certificates, including the private portions, need to be readable
by the *mosquitto* user.

.. _`current versions of mosquitto`: https://mosquitto.org/documentation/migrating-to-2-0/

------------------------
Firewalls and Networking
------------------------

If you're reading this to determine how to access pyDE1 from the open Internet,
you'll have to find other resources on that. To be very clear, even with nginx
reverse proxying the Python HTTP server and running ``mosquitto``, it is not
secure. This is one of those "If you have to ask ..." things.

One piece of firewall worth noting is that ``mosquitto`` apparently can't
restrict the *websockets* listener to the localhost interface.

.. [1] The private key has been named to be consistent with Let's Encrypt naming.
