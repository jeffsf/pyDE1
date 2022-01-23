..
    Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=====================
Configuring nginx
=====================

--------
Overview
--------

``nginx`` is a web server that is widely used in production environments.
An unfortunate effect of serving this market is that it is non-trivial
to configure, due to the great flexibility.

In this example configuration, it is used as a reverse proxy for the Python
HTTP server and the websockets interface provided by ``mosquitto``. It also
demonstrates the kind of configuration that a web app might use for
static files and dynamic content with uWSGI.

.. warning::

    Security should not be taken lightly. Even when "only" exposed on the
    loopback interface, any service poses a vector for attack.

    Although this example shows configuration for TLS, this secures the data
    while in flight and not the service. Users must determine and implement
    appropriate security for their needs.


--------------------
Installing nginx
--------------------

.. code-block:: sh

  apt install nginx


---------------------------
Example nginx Configuration
---------------------------

The default ``/etc/nginx/nginx.conf`` includes a directive to read
configuration from ``/etc/nginx/conf.d/``. However, a couple of lines in
the Debian Bullseye package's version can't be easily overridden.
To minimize and localize the changes, making future, nginx upgrades easier,
these lines are commented out as shown in this ``diff`` output.

.. code-block::

    --- nginx.conf.orig	2021-09-06 09:16:12.021343622 -0700
    +++ nginx.conf	2021-08-30 21:30:36.611817810 -0700
    @@ -29,15 +29,15 @@
        # SSL Settings
        ##

    -	ssl_protocols TLSv1 TLSv1.1 TLSv1.2 TLSv1.3; # Dropping SSLv3, ref: POODLE
    -	ssl_prefer_server_ciphers on;
    +#	ssl_protocols TLSv1 TLSv1.1 TLSv1.2 TLSv1.3; # Dropping SSLv3, ref: POODLE
    +#	ssl_prefer_server_ciphers on;

        ##
        # Logging Settings
        ##

    -	access_log /var/log/nginx/access.log;
    -	error_log /var/log/nginx/error.log;
    +#	access_log /var/log/nginx/access.log;
    +#	error_log /var/log/nginx/error.log;

        ##
        # Gzip Settings


General Configuration
=====================

The first set of configuration is read into the ``http`` block of
``nginx.conf``, before "sites" are read. It applies to all instances.
From the end of the ``http`` block in ``nginx.conf``:

::

  include /etc/nginx/conf.d/*.conf;
  include /etc/nginx/sites-enabled/*;

It is shown here as snippets in multiple files within ``/etc/nginx/conf.d/``
which may be easier to manage using ``git`` or another VCS. The snippets
of the general configuration could be combined into a single file, such as
``/etc/nginx/conf.d/local.conf`` or otherwise arranged as makes sense to you.


Enable On-the-Fly Compression
-----------------------------

Modern browsers can decompress content as it receives it. Compression
can save transmission time, improving overall response time on
lower bandwidth connections. This section enables on-the-fly compression
at the server. This includes, for example, large data sets
for plotting of history.

``conf.d/gzip.conf``

::

  # gzip on;  # Declared on in nginx.conf
  gzip_vary on;
  gzip_proxied any;
  gzip_comp_level 6;
  gzip_buffers 16 8k;
  gzip_http_version 1.1;
  gzip_types text/plain text/css application/json application/javascript
             text/xml application/xml application/xml+rss text/javascript;


Adjust Logging
--------------

These changes modify the logging format from the "CLF" to one with a bit more
information. Note that the error log's format can't be overridden.

``conf.d/logging.conf``

::

 # http://nginx.org/en/docs/http/ngx_http_log_module.html#log_format

 log_format  main_rt  '$remote_addr - $remote_user [$time_local] '
        '"$scheme://$host" "$request" '
        '$status $body_bytes_sent "$http_referer" '
        '"$http_user_agent" "$http_x_forwarded_for" '
        '${request_time}s $sent_http_content_type';

 # http://nginx.org/en/docs/http/ngx_http_log_module.html#access_log
 # http://nginx.org/en/docs/ngx_core_module.html#error_log

 access_log  /var/log/nginx/access.log  main_rt;
 error_log  /var/log/nginx/error.log;   # Can't set format, see above


Set DNS Resolvers
-----------------

For `nginx` to be able to locate the servers that it is proxying,
it needs DNS resolvers. It does not use the OS's notion of resolvers.
These should be set to your *local* resolvers or other resolvers that
are always available.

``conf.d/resolvers.conf``

::

  # replace with the IP address of your resolver(s)
  resolver 192.168.1.1;
  # resolver 192.168.1.1 192.168.1.2;


Reverse Proxying, General Configuration
---------------------------------------

Some of the headers added here may only be of interest if you have another
instance of `nginx` running behind your first-contact instance. They inform
the proxyed server of where the original request came from, which otherwise
would appear to come from this ``nginx`` instance, rather than the remote
browser.

Websockets need some special configuration, as described at
http://nginx.org/en/docs/http/websocket.html

``conf.d/reverse_proxy.conf``

::

  #
  # Setup for reverse proxy
  #

  # https://www.nginx.com/resources/wiki/start/topics/examples/forwarded/
  # talks about the RFC 7239 Forwarded header, but there's no built-in yet
  # also warnings about https://trac.nginx.org/nginx/ticket/1316

  proxy_http_version 1.1;

  # http://nginx.org/en/docs/http/ngx_http_realip_module.html
  # "Should an upstream server be able to set the IP?"
  # Here, no. This is the first point of contact

  map $http_x_forwarded_proto $xfp_set_if_unset {
      ''      $scheme;
      default $http_x_forwarded_proto;
  }

  # http://nginx.org/en/docs/http/websocket.html

  map $http_upgrade $connection_upgrade {
      ''      close;
      default upgrade;
  }

  proxy_set_header        Host $host;
  proxy_set_header        X-Real-IP $remote_addr;
  proxy_set_header        X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header        X-Forwarded-Proto $xfp_set_if_unset;

  proxy_set_header	Upgrade $http_upgrade;
  proxy_set_header	Connection $connection_upgrade;


Enable Keep-Alive
-----------------

Current defaults of 75 seconds and ``tcp_nodelay on`` seem sufficient.
No change appears to be required.

http://nginx.org/en/docs/http/ngx_http_core_module.html#keepalive_timeout
http://nginx.org/en/docs/http/ngx_http_core_module.html#tcp_nodelay


Redirect HTTP to HTTP-S
-----------------------

As ``conf.d/tls.conf``, described later, enables HSTS for all sites,
the redirect should be for all sites as well.

``conf.d/redirect_tls.conf``

.. code-block::

  server {
      listen 80 default_server;
      listen [::]:80 default_server;

      location / {
  	      return 301 https://$host$request_uri;
      }
  }



Configure TLS
-------------

.. warning::

  Users should evaluate and make their own decisions around TLS and other
  security questions.

  These configurations are provided as examples.

Mozilla maintains and has been periodically updating configuration suggestions
at https://wiki.mozilla.org/Security/Server_Side_TLS

The configurations below are based on the generator at
https://ssl-config.mozilla.org/

These were last examined January, 2022.

.. note::

  Recommendations change with time, sometimes quickly when vulnerabilities
  are discovered.

  It is strongly suggested that users periodically check for and implement changes
  in security recommendations.

Using Let's Encrypt Certificates, TLSv1.3 Only, OCSP Stapling, and HSTS
.......................................................................

This configuration requires control over a public domain name to be able to
generate the Let's Encrypt certificates.

TLSv1.3 should be supported by up-to-date devices, but may not be supported
by older OS installs, such as Android without an updated browser. Anything
older than TLSv1.2 should be considered as insecure. For an application like
this with clients typically under your control, if TLSV1.3 isn't supported,
you probably should update the device's software.

    Supports Firefox 63 *(2018)*, Android 10.0 *(2019)*, Chrome 70 *(2018)*,
    Edge 75 *(2019)*, ... , and Safari 12.1 *(2019)*

OCSP (Online Certificate Status Protocol) only makes sense for
publicly verifiable certificates.

HSTS (HTTP Strict Transport Security) informs browsers that the site
should only be accessed using HTTP-S. As it is cached by the browser,
you may want to confirm that the redirect from HTTP to HTTP-S is working
properly before enabling it.

``tls.conf``

.. code-block::

    # https://wiki.mozilla.org/Security/Server_Side_TLS
    # "nginx 1.18.0, modern config, OpenSSL 1.1.1k
    #  Supports Firefox 63, Android 10.0, Chrome 70, Edge 75, Java 11,
    #  OpenSSL 1.1.1, Opera 57, and Safari 12.1"
    # generated 2022-01-22, Mozilla Guideline v5.6, nginx 1.18.0, OpenSSL 1.1.1k, modern configuration
    # https://ssl-config.mozilla.org/#server=nginx&version=1.18.0&config=modern&openssl=1.1.1k&guideline=5.6

    ssl_certificate      certs/fullchain.pem;
    ssl_certificate_key  certs/privkey.pem;
    ssl_session_timeout  1d;
    ssl_session_cache    shared:MozSSL:10m;  # about 40000 sessions
    ssl_session_tickets  off;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;

    # HSTS (ngx_http_headers_module is required) (63072000 seconds, two years)
    add_header Strict-Transport-Security "max-age=63072000" always;

    # OCSP stapling
    ssl_stapling on;
    ssl_stapling_verify on;

    # verify chain of trust of OCSP response using Root CA and Intermediate certs
    # https://community.letsencrypt.org/t/howto-ocsp-stapling-for-nginx/13611/5
    #   "You need to set the ssl_trusted_certificate to chain.pem
    #    for OCSP stapling to work.
    ssl_trusted_certificate certs/chain.pem;


Using Let's Encrypt Certificates, TLSv1.3 and TLSv1.2, OCSP Stapling, and HSTS
..............................................................................

.. warning::

  TLSv1.2 is not considered as secure as TLSv1.3.

  Unless you've got some "ancient" software that can't be upgraded, TLSv1.2
  is not recommended for use where you've got control over important clients.

This configuration relaxes the requirement for TLSv1.3 and permits TLSv1.2.
At this time, anything older than TLSv1.2 is no longer recommended. Should
you have a need for older protocols, please consult the Mozilla references
or other sources directly.

.. note::

  Configuration for TLSv1.2 requires Diffie-Hellman parameters

  ::

    curl https://ssl-config.mozilla.org/ffdhe2048.txt > /etc/nginx/ffdhe2048.txt

``tls.conf``

.. code-block::

  # https://wiki.mozilla.org/Security/Server_Side_TLS
  # "nginx 1.18.0, intermediate config, OpenSSL 1.1.1k
  #  Supports Firefox 27, Android 4.4.2, Chrome 31, Edge, IE 11 on Windows 7,
  #  Java 8u31, OpenSSL 1.0.1, Opera 20, and Safari 9"
  # generated 2022-01-22, Mozilla Guideline v5.6, nginx 1.18.0, OpenSSL 1.1.1k, intermediate configuration
  # https://ssl-config.mozilla.org/#server=nginx&version=1.18.0&config=intermediate&openssl=1.1.1k&guideline=5.6

  ssl_certificate      certs/fullchain.pem;
  ssl_certificate_key  certs/privkey.pem;
  ssl_session_timeout  1d;
  ssl_session_cache    shared:MozSSL:10m;  # about 40000 sessions
  ssl_session_tickets  off;

  # curl https://ssl-config.mozilla.org/ffdhe2048.txt > /etc/nginx/ffdhe2048.txt
  ssl_dhparam /etc/nginx/ffdhe2048.txt;

  # intermediate configuration
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
  ssl_prefer_server_ciphers off;

  # HSTS (ngx_http_headers_module is required) (63072000 seconds, two years)
  add_header Strict-Transport-Security "max-age=63072000" always;

  # OCSP stapling
  ssl_stapling on;
  ssl_stapling_verify on;

  # verify chain of trust of OCSP response using Root CA and Intermediate certs
  # ssl_trusted_certificate /path/to/root_CA_cert_plus_intermediates;
  ## verify chain of trust of OCSP response using Root CA and Intermediate certs
  # https://community.letsencrypt.org/t/howto-ocsp-stapling-for-nginx/13611/5
  #   "You need to set the ssl_trusted_certificate to chain.pem
  #    for OCSP stapling to work.
  ssl_trusted_certificate certs/chain.pem;


Using Self-Signed Certificates, TLSv1.3 Only, and HSTS
......................................................

Although self-signed certificates present challenges including getting modern
browsers to accept them, users without control over a public domain name aren't
able to obtain publicly verifiable certificates. See
:ref:`Security > Self-Signed Certificates<security_self-signed_certificates>`
for more information. As previously noted, OCSP (Online Certificate Status
Protocol) doesn't make sense for self-signed certificates.

``tls.conf``

.. code-block::

    # https://wiki.mozilla.org/Security/Server_Side_TLS
    # "nginx 1.18.0, modern config, OpenSSL 1.1.1k
    #  Supports Firefox 63, Android 10.0, Chrome 70, Edge 75, Java 11,
    #  OpenSSL 1.1.1, Opera 57, and Safari 12.1"
    # generated 2022-01-22, Mozilla Guideline v5.6, nginx 1.18.0, OpenSSL 1.1.1k, modern configuration
    # https://ssl-config.mozilla.org/#server=nginx&version=1.18.0&config=modern&openssl=1.1.1k&guideline=5.6

    ssl_certificate      certs/cert.pem;
    ssl_certificate_key  certs/privkey.pem;
    ssl_session_timeout  1d;
    ssl_session_cache    shared:MozSSL:10m;  # about 40000 sessions
    ssl_session_tickets  off;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;

    # HSTS (ngx_http_headers_module is required) (63072000 seconds, two years)
    add_header Strict-Transport-Security "max-age=63072000" always;


Site Configuration
==================

Linux-based OSes seem to use a ``sites-available`` / ``sites-enabled``
configuration approach. With this approach, the configuration is kept
in ``sites-available`` and a symlink is placed in ``sites-enabled``
for those that should be used for the starting or reloading instance.

Once you have confirmed that ``nginx`` is running properly, remove the
symlink in ``sites-enabled/`` to ``default``. Once configured, a symlink
to ``../sites-available/pyde1`` in ``sites-enabled/`` will use the new
configuration on the next restart of ``nginx``.


Main Server Block
-----------------

This is the body of the configuration. The ``server_name`` must be one that
corresponds to that of the TLS certificate. TLS generally "won't work" with
a numeric IP address in the address bar. Configuration of local DNS is outside
the scope of these instructions. Please consult your "router" instructions.

This block does the following:

* Sets up a listener on port 443 for HTTP-S connections to ``www.example.com``

* Sets the cache expiration to be immediate. This can be removed when your
  development phase is complete and you are not changing content files.

* ``location ~ /\.`` – Prohibit access to ``.git`` or the like

* ``location /favicon.ico`` – Don't log its absence

* ``location /pyde1/`` – Proxy to the Python, HTTP server

* ``location /de1-plot/ws`` – Proxy to the ``mosquitto`` WebSocket port
  (location specific to external web-app config)

* ``location /de1-plot/db`` – Proxy to the uWSGI server socket
  (location specific to external web-app config)

``sites-available/pyde1.conf``

.. code-block::

  server {
      listen 443 ssl http2;
      listen [::]:443 ssl http2;
      server_name www.example.com;

      root /var/www/html;

      # Do not cache while doing development
      # http://nginx.org/en/docs/http/ngx_http_headers_module.html#expires
      # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
      expires	0;

      # This seems to work, but not ^~
      location ~ /\. {
          return 404;
      }

      location / {
          index  index.html index.htm;
      }

      location /favicon.ico {
          log_not_found off;
      }

      location /pyde1/ {
          proxy_pass http://127.0.0.1:1234/ ;
      }

      location /de1-plot/ws {
          proxy_pass http://127.0.0.1:1884/ ;
      }

      # http://nginx.org/en/docs/http/ngx_http_rewrite_module.html#set

      location /de1-plot/db/ {

          # The "obvious" doesn't work
          # rewrite /de1-plot/db/(.*) /$1 break;

          include uwsgi_params;
          set $rewritten_uri $request_uri;
          if ($request_uri ~ /de1-plot/db/(.*)) {
              set $rewritten_uri /$1;
          }
          uwsgi_param REQUEST_URI $rewritten_uri;
          uwsgi_pass unix:///tmp/uwsgi-pyde1-db.sock;
      }
  }

Change Site From "default" to "pyde1"
-------------------------------------

To enable the "pyde1" site definition, remove the *symlink* to ``default`` in ``sites-enabled``
and link in the new ``pyde1`` (or whatever you've called it).

::

    jeff@pi-walnut:/etc/nginx/sites-enabled $ ls -l
    total 0
    lrwxrwxrwx 1 root root 26 Nov 20 14:13 default -> ../sites-available/default
    jeff@pi-walnut:/etc/nginx/sites-enabled $ sudo rm default
    jeff@pi-walnut:/etc/nginx/sites-enabled $ sudo ln -s ../sites-available/pyde1 .
    jeff@pi-walnut:/etc/nginx/sites-enabled $ ls -l
    total 0
    lrwxrwxrwx 1 root root 24 Nov 20 14:14 pyde1 -> ../sites-available/pyde1

.. note::

  ``sudo nginx -t -c /etc/nginx/nginx.conf`` can be used to test configuration

  Remember to ``sudo systemctl restart nginx.service``
  to have the changes take effect.
