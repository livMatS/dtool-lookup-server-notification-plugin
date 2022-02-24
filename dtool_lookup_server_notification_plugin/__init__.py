import ipaddress
from functools import wraps

import dtoolcore
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

from .config import Config

try:
    from importlib.metadata import version, PackageNotFoundError
except ModuleNotFoundError:
    from importlib_metadata import version, PackageNotFoundError

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass

AFFIRMATIVE_EXPRESSIONS = ['true', '1', 'y', 'yes', 'on']


def filter_ips(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if ipaddress.ip_address(request.remote_addr) in \
                Config.ALLOW_ACCESS_FROM:
            return f(*args, **kwargs)
        else:
            return abort(403)

    return wrapped


def _parse_obj_key(key):
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
    for dataset, base_uri in query_result:
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
    mongo.db[MONGO_COLLECTION].remove({"uri": {"$eq": uri}})



