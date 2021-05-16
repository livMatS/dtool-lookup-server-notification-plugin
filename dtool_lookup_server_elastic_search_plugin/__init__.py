import json
import os

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
    get_jwt_identity,
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
    BUCKET_TO_BASE_URI = json.loads(
        os.environ.get('DTOOL_LOOKUP_SERVER_NOTIFY_BUCKET_TO_BASE_URI',
                       '{"bucket": "s3://bucket"}'))

    @classmethod
    def to_dict(cls):
        """Convert server configuration into dict."""
        d = {'version': __version__}
        for k, v in cls.__dict__.items():
            # select only capitalized fields
            if k.upper() == k:
                d[k.lower()] = v
        return d


@elastic_search_bp.route("/notify/all/<path:objpath>", methods=["POST"])
def notify_create_or_update(objpath):
    """Notify the lookup server about creation of a new object or modification
    of an object's metadata."""
    json = request.get_json()

    # The metadata is only attached to the 'dtool' object of the respective
    # UUID and finalizes creation of a dataset. We can register that dataset
    # now.
    if 'metadata' in json:
        admin_metadata = json['metadata']

        if 'name' in admin_metadata and 'uuid' in admin_metadata:
            bucket = json['bucket']

            base_uri = Config.BUCKET_TO_BASE_URI[bucket]

            dataset_uri = dtoolcore._generate_uri(admin_metadata, base_uri)

            current_app.logger.info('Registering dataset with URI {}'.format(dataset_uri))

            dataset = dtoolcore.DataSet.from_uri(dataset_uri)
            dataset_info = generate_dataset_info(dataset, base_uri)
            register_dataset(dataset_info)

    return jsonify({})


def delete_dataset(base_uri, uuid):
    """Delete a dataset in the lookup server."""
    if not base_uri_exists(base_uri):
        raise(ValidationError(
            "Base URI is not registered: {}".format(base_uri)
        ))

    # Query database to construct the respective URI
    uris = []
    query_result = sql_db.session.query(Dataset, BaseURI)  \
        .filter(Dataset.uuid == uuid)  \
        .filter(BaseURI.id == Dataset.base_uri_id)  \
        .filter(BaseURI.base_uri == base_uri)
    for dataset, base_uri in query_result:
        uris += [dtoolcore._generate_uri(
            {'uuid': dataset.uuid, 'name': dataset.name}, base_uri.base_uri)]

    # Delete datasets with this URI
    sql_db.session.query(Dataset)  \
        .filter(Dataset.uri.in_(uris))  \
        .delete()
    sql_db.session.commit()

    # Remove from Mongo database
    mongo.db[MONGO_COLLECTION].remove({"uri": {"$in": uris}})


@elastic_search_bp.route("/notify/all/<path:objpath>", methods=["DELETE"])
def notify_delete(objpath):
    """Notify the lookup server about deletion of an object."""

    # The only information that we get is the URL. We need to convert the URL
    # into the respective UUID of the dataset.
    url = request.url

    # Delete dataset if the `dtool` object is deleted
    if url.endswith('/dtool'):
        # The URL has the form
        #     https://<server-name>/elastic-search/notify/all/<bucket-name>_<uuid>/dtool
        # or
        #     https://<server-name>/elastic-search/notify/all/<bucket-name>_<prefix><uuid>/dtool
        uuid = objpath[-42:-6]
        base_uri = None
        for bucket, uri in Config.BUCKET_TO_BASE_URI.items():
            if objpath.startswith(bucket):
                base_uri = uri
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
