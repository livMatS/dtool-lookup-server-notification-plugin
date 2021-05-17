import ipaddress
import json
import os
from functools import wraps

import dtoolcore
from flask import (
    abort,
    Blueprint,
    current_app,
    jsonify,
    request
)
from flask_jwt_extended import (
    jwt_required,
)
from dtool_lookup_server import (
    mongo,
    sql_db,
    AuthenticationError,
    ValidationError,
    MONGO_COLLECTION,
)
from dtool_lookup_server.sql_models import (
    BaseURI,
    Dataset,
)
from dtool_lookup_server.utils import (
    base_uri_exists,
    generate_dataset_info,
    register_dataset,
)

AFFIRMATIVE_EXPRESSIONS = ['true', '1', 'y', 'yes', 'on']

try:
    from importlib.metadata import version, PackageNotFoundError
except ModuleNotFoundError:
    from importlib_metadata import version, PackageNotFoundError

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass

elastic_search_bp = Blueprint("elastic-search", __name__, url_prefix="/elastic-search")


class Config(object):
    # Dictionary for conversion of bucket names to base URIs
    BUCKET_TO_BASE_URI = json.loads(
        os.environ.get('DTOOL_LOOKUP_SERVER_NOTIFY_BUCKET_TO_BASE_URI',
                       '{"bucket": "s3://bucket"}'))

    # Limit notification access to IPs starting with this string
    ALLOW_ACCESS_FROM = ipaddress.ip_network(
        os.environ.get('DTOOL_LOOKUP_SERVER_NOTIFY_ALLOW_ACCESS_FROM',
                       '0.0.0.0/0'))  # Default is access from any IP

    @classmethod
    def to_dict(cls):
        """Convert server configuration into dict."""
        d = {'version': __version__}
        for k, v in cls.__dict__.items():
            # select only capitalized fields
            if k.upper() == k:
                if isinstance(v, ipaddress.IPv4Network) or \
                        isinstance(v, ipaddress.IPv6Network):
                    v = str(v)
                d[k.lower()] = v
        return d


def filter_ips(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if ipaddress.ip_address(request.remote_addr) in \
                Config.ALLOW_ACCESS_FROM:
            return f(*args, **kwargs)
        else:
            return abort(403)

    return wrapped


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

    components = objpath_without_bucket.split('/')
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


@elastic_search_bp.route("/notify/all/<path:objpath>", methods=["POST"])
@filter_ips
def notify_create_or_update(objpath):
    """Notify the lookup server about creation of a new object or modification
    of an object's metadata."""
    json = request.get_json()
    if json is None:
        abort(400)

    dataset_uri = None

    # The metadata is only attached to the 'dtool' object of the respective
    # UUID and finalizes creation of a dataset. We can register that dataset
    # now.
    if 'metadata' in json:
        admin_metadata = json['metadata']

        if 'name' in admin_metadata and 'uuid' in admin_metadata:
            bucket = json['bucket']

            base_uri = Config.BUCKET_TO_BASE_URI[bucket]

            dataset_uri = dtoolcore._generate_uri(admin_metadata, base_uri)

            current_app.logger.info('Registering dataset with URI {}'
                                    .format(dataset_uri))
    else:
        base_uri, uuid, kind = _parse_objpath(objpath)
        # We also need to update the database if the metadata has changed.
        if kind in ['README.yml', 'tags', 'annotations']:
            dataset_uri = _retrieve_uri(base_uri, uuid)

    if dataset_uri is not None:
        try:
            dataset = dtoolcore.DataSet.from_uri(dataset_uri)
            dataset_info = generate_dataset_info(dataset, base_uri)
            register_dataset(dataset_info)
        except dtoolcore.DtoolCoreTypeError:
            # DtoolCoreTypeError is raised if this is not a dataset yet, i.e.
            # if the dataset has only partially been copied. There will be
            # another notification once everything is final. We simply
            # ignore this.
            current_app.logger.debug('DtoolCoreTypeError raised for dataset '
                                     'with URI {}'.format(dataset_uri))
            pass

    return jsonify({})


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


@elastic_search_bp.route("/notify/all/<path:objpath>", methods=["DELETE"])
@filter_ips
def notify_delete(objpath):
    """Notify the lookup server about deletion of an object."""
    # The only information that we get is the URL. We need to convert the URL
    # into the respective UUID of the dataset.
    url = request.url

    # Delete dataset if the `dtool` object is deleted
    if url.endswith('/dtool'):
        base_uri, uuid, kind = _parse_objpath(objpath)
        assert kind == 'dtool'
        delete_dataset(base_uri, uuid)

    return jsonify({})


@elastic_search_bp.route("/_cluster/health", methods=["GET"])
def health():
    """This route is used by the S3 storage to test whether the URI exists."""
    return jsonify({})


@elastic_search_bp.route("/config", methods=["GET"])
@jwt_required
def plugin_config():
    """Return the JSON-serialized elastic search plugin configuration."""
    try:
        config = Config.to_dict()
    except AuthenticationError:
        abort(401)
    return jsonify(config)
