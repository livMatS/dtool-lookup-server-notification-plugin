import ipaddress
import json
import logging
import re
from functools import wraps

import dtoolcore, dtool_s3
from flask import (
    abort,
    current_app,
    request
)

from dtool_lookup_server import (
    mongo,
    sql_db,
    ValidationError,
    MONGO_COLLECTION,
)
from dtool_lookup_server.sql_models import (
    BaseURI,
    Dataset,
)
from dtool_lookup_server.utils import (
    base_uri_exists,
)

try:
    from importlib.metadata import version, PackageNotFoundError
except ModuleNotFoundError:
    from importlib_metadata import version, PackageNotFoundError

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    # package is not installed
    __version__  = None

if __version__ is None:
    try:
        del __version__
        from .version import __version__
    except:
        __version__ = None


from .config import Config

AFFIRMATIVE_EXPRESSIONS = ['true', '1', 'y', 'yes', 'on']
UUID_REGEX_PATTERN = '[0-9A-F]{8}-[0-9A-F]{4}-[4][0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}'
UUID_REGEX = re.compile(UUID_REGEX_PATTERN, re.IGNORECASE)

logger = logging.getLogger(__name__)


def _log_nested(log_func, dct):
    for l in json.dumps(dct, indent=2, default=str).splitlines():
        log_func(l)


def filter_ips(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        ip = ipaddress.ip_address(request.remote_addr)
        logger.info("Accessed from %s", ip)
        if ip in Config.ALLOW_ACCESS_FROM:
            return f(*args, **kwargs)
        else:
            return abort(403)

    return wrapped


def _parse_obj_key(key):
    # Just looking at the end of the key is a bit risky, you might find
    # anything below the data prefix, including another wrapped dataset, hence:
    # TODO: check for relative position below top-level
    components = key.split('/')
    if len(components) > 1:
        if components[-2] in ['data', 'tags', 'annotations']:
            # The UUID is the component before 'data'
            uuid = components[-3]
            kind = components[-2]
        else:
            # No data entry, the UUID is the second to last component
            uuid = components[-2]
            kind = components[-1]
    else:
        if components[0].startswith('dtool-'):
            # This is the registration key
            uuid = components[0][6:]
            kind = '__REGISTRATION_KEY__'
        else:
            kind = None
            uuid = None

    return uuid, kind


def _parse_objpath(objpath):
    """
    Extract base URI and UUID from the URL. The URL has the form
        https://<server-name>/elastic-search/notify/all/<bucket-name>_<uuid>/dtool
    or
        https://<server-name>/elastic-search/notify/all/<bucket-name>_<prefix><uuid>/dtool
    The objpath is the last part of the URL that follows /notify/all/.
    """
    base_uri = None
    objpath_without_bucket = None
    for bucket, uri in Config.BUCKET_TO_BASE_URI.items():
        if objpath.startswith(bucket):
            base_uri = uri
            # +1 because there is an underscore after the bucket name
            objpath_without_bucket = objpath[len(bucket)+1:]

    uuid, kind = _parse_obj_key(objpath_without_bucket)

    return base_uri, uuid, kind


def _reconstruct_uri(base_uri, object_key):
    """Reconstruct dataset URI on S3 bucket from bucket name and object key."""
    # The expected structure of an object key (without preceding bucket name)
    # is either
    #   dtool-{UUID}
    # for the top-level "link" object or
    #   [{arbitrary_prefix}/]{UUID}[/{other_arbitrary_suffix}]
    # There are now several to infer the URI of a dataset.
    # The important key point is that all dtool-processible URIs
    # point to the bucket top level, no matter whether the actual dataset
    # resides at top-level as well or below some other prefix. This means
    #   s3://test-bucket/49f0bf41-471b-4781-855e-161fe81ffb0d
    # may point to a dataset actually residing at
    #   s3://test-bucket/49f0bf41-471b-4781-855e-161fe81ffb0d
    # or below some arbitrary prefix, i.e.
    #   s3://test-bucket/u/test-user/49f0bf41-471b-4781-855e-161fe81ffb0d
    # resolved by the content of the top-level "link" object
    #   s3://test-bucket/dtool-49f0bf41-471b-4781-855e-161fe81ffb0d
    # Seemingly, the straight forward approach would be to only evaluate
    # top-level dtool-{UUID} objects and infer the URI as
    #   s3://{BUCKET_NAME}/{UUID}
    # As we must not make any assumptions on the order of object creation,
    # a notification about a new dtool-{UUID} does not mean the availability
    # of a healthy dataset fit for registration. Beyond that, updates to
    # a dataset may not touch the dtool-{UUID} object. Instead, we try to infer
    # the UUID of the containing dataset for every object notification, check
    # whether a dataset has been registered already with the according
    # combination of base URI and UUID, retrieve the correct dataset URI from
    # the index in this case, or just construct it by concatenating base URI
    # and UUID as
    #   {BASE_URI}/{UUID}
    # Note that the mapping (BASE_URI, UUID) <-> URI is only bijective
    # for the s3 storage broker. It cannot be generalized to other storage.
    # We need to find the dataset UUID in the obejct key. A viable approach
    # is to just look for the first valid v4 UUID in the string. This would
    # conflict with a prefix that contains a v4 UUID as well.

    uuid_match = UUID_REGEX.search(object_key)
    if uuid_match is None:
        # This should not happen, all s3 objects created via dtool
        # must have a valid UUID within its object key.
        raise ValueError("The object key %s does not contain any valid UUID.", object_key)

    uuid = uuid_match.group(0)
    logger.debug("Extracted UUID '%s' from object key '%s'.", uuid, object_key)

    # check whether this (BASE_URI, UUID) combination has been registered before
    uri = _retrieve_uri(base_uri, uuid)

    if uri is None:
        # instead of using the dtoolcore._generate_uri proxy, we explicitly
        # use the dtool_s3.storagebroker.S3StorageBroker.generate_uri class
        # method as we know the name does not play a role here.
        # uri = dtool_s3.storagebroker.S3StorageBroker.generate_uri(
        #     name='dummy', uuid=uuid, base_uri=base_uri)
        # instead of the explicit use of dtool_s3 above, we revert to the
        # following
        return dtoolcore._generate_uri({'uuid': uuid, 'name': uuid}, base_uri)
        # just to make our current tests pass.
        # TODO: kick out dtoolcore._generate_uri once we have proper S3-based tests

        logger.debug(("Dataset has not been registered yet, "
                      "reconstructed URI '%s' from base URI '%s' and UUID '%s'."),
                     uri, base_uri, uuid)
    else:
        logger.debug("Dataset registered before under URI '%s'.", uri)

    return uri


def _retrieve_uri(base_uri, uuid):
    """Retrieve URI(s) from database given as base URI and an UUID"""
    if not base_uri_exists(base_uri):
        raise(ValidationError(
            "Base URI is not registered: {}".format(base_uri)
        ))

    # Query database to construct the respective URI. We cannot just
    # concatenate base URI and UUID since the URI may depend on the name of
    # the dataset which we do not have.
    uris = []
    query_result = sql_db.session.query(Dataset, BaseURI)  \
        .filter(Dataset.uuid == uuid)  \
        .filter(BaseURI.id == Dataset.base_uri_id)  \
        .filter(BaseURI.base_uri == base_uri)
    logger.debug("Query result:")
    _log_nested(logger.debug, query_result)

    for dataset, base_uri in query_result:
        # this general treatment makes sense for arbitrary storage brokers, but
        # for the current (2022-02) implementation of the s3 broker, the actual
        # dataset name is irrelevant for the URI. Furthermore. there should
        # always be only one entry for a particular (BASE_URI, UUID) tuple
        # on an s3 bucket.
        return dtoolcore._generate_uri(
            {'uuid': dataset.uuid, 'name': dataset.name}, base_uri.base_uri)

    return None


def delete_dataset(base_uri, uuid):
    """Delete a dataset in the lookup server."""
    uri = _retrieve_uri(base_uri, uuid)
    current_app.logger.info('Deleting dataset with URI {}'.format(uri))

    # Delete datasets with this URI
    sql_db.session.query(Dataset)  \
        .filter(Dataset.uri == uri)  \
        .delete()
    sql_db.session.commit()

    # Remove from Mongo database
    # https://pymongo.readthedocs.io/en/stable/api/pymongo/collection.html#pymongo.collection.Collection.delete_one
    mongo.db[MONGO_COLLECTION].delete_one({"uri": {"$eq": uri}})
