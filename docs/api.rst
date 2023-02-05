..
    Copyright © 2021 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

===
API
===


There are three, versioned, supported APIs for pyDE1. These include an HTTP
server for querying and setting of parameters, an MQTT service for obtaining
real-time updates, and an SQLite3 database allowing concurrent access to history.

With these APIs and the configuration files, there should be no need
to access code internals. If there is missing functionality, please
`file an enhancement request`_ including the use case that you wish
to satisfy.

.. _`file an enhancement request`: https://github.com/jeffsf/pyDE1/issues

The code internals are subject to change and should not be relied on as an API.

Semantic versioning is available for the HTTP and MQTT APIs. Changes are noted
in the commit logs, as well as in the CHANGELOG. Breaking changes (those that
are not backwards-compatible) will increment the major version. Details of how
to obtain the running version are described in the detailed sections for each
of the APIs.

The database schema is available through ``PRAGMA user_version``. It is an
incrementing integer. Although it is hoped that schema changes will be
backwards compatible, checking the commit logs and CHANGELOG is suggested
for authors of applications that directly access the database.

.. toctree::
    :maxdepth: 3

    api_http
    api_mqtt
    api_database
    profile_json
