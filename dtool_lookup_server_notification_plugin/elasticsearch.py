import json
import os

import dtoolcore

from dtool_lookup_server import AuthenticationError
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

from dtool_lookup_server.utils import (
    generate_dataset_info,
    register_dataset,
)

from .config import Config
from . import (
    delete_dataset,
    filter_ips,
    _parse_objpath,
    _retrieve_uri
)


elastic_search_bp = Blueprint("elastic-search", __name__, url_prefix="/elastic-search")


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
@jwt_required()
def plugin_config():
    """Return the JSON-serialized elastic search plugin configuration."""
    try:
        config = Config.to_dict()
    except AuthenticationError:
        abort(401)
    return jsonify(config)