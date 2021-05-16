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
from dtool_lookup_server import AuthenticationError
from dtool_lookup_server.utils import (
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


@elastic_search_bp.route("/notify/all/<path:objpath>", methods=["DELETE"])
def notify_delete(objpath):
    """Notify the lookup server about deletion of an object."""
    json = request.get_json()

    print('DELETE request')
    print(json)

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
