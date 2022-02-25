Dtool Lookup Server Notification Plugin
=======================================

- GitHub: https://github.com/livMatS/dtool-lookup-server-notification-plugin
- PyPI: https://pypi.python.org/pypi/dtool-lookup-server-notification-plugin
- Free software: MIT License


Features
--------

- Listen to elastic search notifications from an S3-compatible storage backend
- Listen to `S3 event notifications <https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html>`_
  from an S3-compatible storage backend


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

This plugin enables the dtool-lookup-server to listen to
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
environment variable ``DTOOL_LOOKUP_SERVER_NOTIFY_BUCKET_TO_BASE_URI`` is used
to specify that conversion, e.g.::

    DTOOL_LOOKUP_SERVER_NOTIFY_BUCKET_TO_BASE_URI={"bucket": "ecs://bucket"}

It is also advisable to limit access to the notification listener to a certain
IP range. Use::

    DTOOL_LOOKUP_SERVER_NOTIFY_ALLOW_ACCESS_FROM=192.168.0.0/16

to specify the allowed remote network. To specify a single IP, use::

    DTOOL_LOOKUP_SERVER_NOTIFY_ALLOW_ACCESS_FROM=192.168.1.1/32

Configure elastic search integration in NetApp StorageGRID
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Create a new endpoint with URI ``https://myserver:myport/elastic-search``
and URN ``arn:<mysite>:es:::<domain-name>/notify/all``

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


Configure webhook in minio
^^^^^^^^^^^^^^^^^^^^^^^^^^

The `Publish Events to Webhook minio docs
<https://docs.min.io/minio/baremetal/monitoring/bucket-notifications/publish-events-to-webhook.html>`_
walks through the configuration for sending S3 event notifications to a webhook.
Assuming a *dtool-lookup-server* with this plugin activated running at
``http://dtool-lookup-server:5000``, and your minio instance with a
bucket ``test-bucket`` at ``https://s3server:9000``, use

.. code-block:: bash

    # mc: minio client
    mc config host add s3server http://s3server:9000 {admin_user} {admin_password}

    # Note that the endpoint must be reachable when configuring, otherwise minio will reject
    mc admin config set s3server/ notify_webhook:dtool  endpoint="http://dtool-lookup-server:5000/webhook/notify"
    mc admin service restart s3server  # restart is necessary

    # Activate the actual notifications
    mc event add s3server/test-bucket arn:minio:sqs::testbucket:dtool --event "put,delete"

to configure a webhook endpoint identified by ``dtool`` and activate ``put`` and
``delete`` event notification.
Choose the parameters for ``--event "put,delete"`` from minio's
`Supported Bucket Evenets <https://docs.min.io/minio/baremetal/reference/minio-mc/mc-event-add.html#mc-event-supported-events>`_.

Note that minio is very strict on whom they talk to. If your `dtool-lookup-server`
communicates via `https`, make sure that the server certificate uses `SANs
<https://en.wikipedia.org/wiki/Subject_Alternative_Name>`_ and that the
signing authority's root certificate is available to minio. See
`Install Certificates from Third-party CAs
<https://docs.min.io/docs/how-to-secure-access-to-minio-server-with-tls.html>`_
in the minio docs. Also assure all services are reachable by valid hostnames.
Within a containerized environment such as launched with `docker-compose` ,
host names containing underscores ``_`` may occur, but minio refuses to speak with
such.

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

Testing
-------

Launch a minimal mongodb instance with

.. code-block:: bash

    $ cd tests/container && docker-compose up -d

and run tests from within repository root using

.. code-block:: bash

    pytest --log-cli-level=DEBUG

Refer to ``.github/workflows/test.yml`` for the recommended testing environment.

Related repositories
--------------------

- `dtool-s3 <https://github.com/jic-dtool/dtool-s3>`_ - storage broker interface to S3 object storage
- `dtool-ecs <https://github.com/jic-dtool/dtool-ecs>`_ - storage broker interface to ECS S3 object storage
