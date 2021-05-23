Dtool Lookup Server Notification Plugin
=======================================

- GitHub: https://github.com/IMTEK-Simulation/dtool-lookup-server-notification-plugin
- PyPI: https://pypi.python.org/pypi/dtool-lookup-server-notification-plugin
- Free software: MIT License


Features
--------

- Listen to elastic search notifications from an S3-compatible storage backend


Introduction
------------

`dtool <https://dtool.readthedocs.io>`_ is a command line tool for packaging
data and metadata into a dataset. A dtool dataset manages data and metadata
without the need for a central database.

However, if one has to manage more than a hundred datasets it can be helpful
to have the datasets' metadata stored in a central server to enable one to
quickly find datasets of interest.

The `dtool-lookup-server <https://github.com/jic-dtool/dtool-lookup-server>`_
provides a web API for registering datasets' metadata
and provides functionality to lookup, list and search for datasets.

This plugin enables the dtool-lookup-server to listen to elastic search
notifications for the registration and deregistration of datasets.


Installation
------------

Install the dtool lookup server dependency graph plugin

.. code-block:: bash

    $ pip install dtool-lookup-server-notification-plugin

Setup and configuration
-----------------------

Configure plugin behavior
^^^^^^^^^^^^^^^^^^^^^^^^^

The plugin needs to know how to convert a bucket name into a base URI. The
environment variable `DTOOL_LOOKUP_SERVER_NOTIFY_BUCKET_TO_BASE_URI` is used
to specify that conversion, e.g.::

    DTOOL_LOOKUP_SERVER_NOTIFY_BUCKET_TO_BASE_URI={"bucket": "ecs://bucket"}

It is also advisable to limit access to the notification listener to a certain
IP range. Use::

    DTOOL_LOOKUP_SERVER_NOTIFY_ALLOW_ACCESS_FROM=192.168.0.0/16

to specify the allowed remote network. To specify a single IP, use::

    DTOOL_LOOKUP_SERVER_NOTIFY_ALLOW_ACCESS_FROM=192.168.1.1/32

Configure elastic search integration in NetApp StorageGRID
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Create a new endpoint with URI
```
https://myserver:myport/elastic-search
```
and URN
```
arn:<mysite>:es:::<domain-name>/notify/all
```
Note that `<mysite>` and `<domain-name>` can be chose arbitrarily.
`notify/all` is appended to the URI and must point to the route of
the notify function.

The bucket needs to be configured to support search integration. Use the
following XML template

.. code-block:: xml

    <MetadataNotificationConfiguration>
        <Rule>
            <ID>dtool</ID>
            <Status>Enabled</Status>
            <Prefix></Prefix>
            <Destination>
               <Urn>urn:mysite:es:::domain-name/notify/all</Urn>
            </Destination>
        </Rule>
    </MetadataNotificationConfiguration>


Querying server plugin configuration
------------------------------------

The request

.. code-block:: bash

    $ curl -H "$HEADER" http://localhost:5000/elastic-search/config

will return the current notification plugin configuration with all keys in lowercase

.. code-block:: json

    {
      "allow_access_from": "0.0.0.0/0",
      "bucket_to_base_uri": {"bucket": "s3://bucket"},
      "version": "0.1.0"
    }


See ``dtool_lookup_server_dependency_graph_plugin.config.Config`` for more information.

Related repositories
--------------------

- `dtool-s3 <https://github.com/jic-dtool/dtool-s3>`_ - storage broker interface to S3 object storage
- `dtool-ecs <https://github.com/jic-dtool/dtool-ecs>`_ - storage broker interface to ECS S3 object storage
