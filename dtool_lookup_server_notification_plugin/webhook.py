"""Receive and process Amazon S3 event notifications."""
import json
import logging
import urllib

from flask import (
    abort,
    Blueprint,
    jsonify,
    request
)

from flask_jwt_extended import (
    jwt_required,
)

import dtoolcore

from dtool_lookup_server import (
    AuthenticationError,
    mongo,
    sql_db,
    MONGO_COLLECTION
)
from dtool_lookup_server.sql_models import (
    Dataset,
)
from dtool_lookup_server.utils import (
    generate_dataset_info,
    register_dataset,
)

from .config import Config
from . import (
    filter_ips,
    _log_nested,
    _parse_obj_key,
    _reconstruct_uri
)

# event names from https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-how-to-event-types-and-destinations.html
OBJECT_CREATED_EVENT_NAMES = [
    's3:ObjectCreated:Put',
    's3:ObjectCreated:Post',
    's3:ObjectCreated:Copy',
    's3:ObjectCreated:CompleteMultipartUpload',
    'ObjectCreated:Put',  # NetApp Storage GRID via SNS endpoint uses event names without s3 prefix
    'ObjectCreated:Post',
    'ObjectCreated:Copy',
    'ObjectCreated:CompleteMultipartUpload'
]


OBJECT_REMOVED_EVENT_NAMES = [
    's3:ObjectRemoved:Delete',
    's3:ObjectRemoved:DeleteMarkerCreated',
    'ObjectRemoved:Delete',  # NetApp Storage GRID via SNS endpoint uses event names without s3 prefix
    'ObjectRemoved:DeleteMarkerCreated'
]

# expected event structure from
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html
# {
#    "Records":[
#       {
#          "eventVersion":"2.2",
#          "eventSource":"aws:s3",
#          "awsRegion":"us-west-2",
#          "eventTime":"The time, in ISO-8601 format, for example, 1970-01-01T00:00:00.000Z, when Amazon S3 finished processing the request",
#          "eventName":"event-type",
#          "userIdentity":{
#             "principalId":"Amazon-customer-ID-of-the-user-who-caused-the-event"
#          },
#          "requestParameters":{
#             "sourceIPAddress":"ip-address-where-request-came-from"
#          },
#          "responseElements":{
#             "x-amz-request-id":"Amazon S3 generated request ID",
#             "x-amz-id-2":"Amazon S3 host that processed the request"
#          },
#          "s3":{
#             "s3SchemaVersion":"1.0",
#             "configurationId":"ID found in the bucket notification configuration",
#             "bucket":{
#                "name":"bucket-name",
#                "ownerIdentity":{
#                   "principalId":"Amazon-customer-ID-of-the-bucket-owner"
#                },
#                "arn":"bucket-ARN"
#             },
#             "object":{
#                "key":"object-key",
#                "size":"object-size in bytes",
#                "eTag":"object eTag",
#                "versionId":"object version if bucket is versioning-enabled, otherwise null",
#                "sequencer": "a string representation of a hexadecimal value used to determine event sequence, only used with PUTs and DELETEs"
#             }
#          },
#          "glacierEventData": {
#             "restoreEventData": {
#                "lifecycleRestorationExpiryTime": "The time, in ISO-8601 format, for example, 1970-01-01T00:00:00.000Z, of Restore Expiry",
#                "lifecycleRestoreStorageClass": "Source storage class for restore"
#             }
#          }
#       }
#    ]
# }
#
# if NetApp storage grid is configured for an SNS endpoint, it does not
# directly submit content of type 'application/json', but instead
# 'application/x-www-form-urlencoded'. request.form has the structure
# {
#   "server": [
#   "Action": "Publish",
#   "Message": "{...}",
#   "TopicArn": "urn:test:sns:test:test:test",
#     "0.0.0.0",
#   "Version": "2010-03-31"
# }
#
# and includes an S3 event notification of above standard within 'Message'
#
# {
#   "Records": [
#     {
#       "eventVersion": "2.0",
#       "eventSource": "sgws:s3",
#       "eventTime": "2022-03-09T12:30:21Z",
#       "eventName": "ObjectCreated:Put",
#       "userIdentity": {
#         "principalId": "80888526281258163395"
#       },
#       "requestParameters": {
#         "sourceIPAddress": "132.230.239.200"
#       },
#       "responseElements": {
#         "x-amz-request-id": "1646829021003401"
#       },
#       "s3": {
#         "s3SchemaVersion": "1.0",
#         "configurationId": "Object created test",
#         "bucket": {
#           "name": "frct-livmats",
#           "ownerIdentity": {
#             "principalId": "80888526281258163395"
#           },
#           "arn": "urn:sgws:s3:::frct-livmats"
#         },
#         "object": {
#           "key": "u/jh1130/481b1bc4-f867-4580-b5d3-28fd7e64a107/dtool",
#           "size": 233,
#           "eTag": "e999ae313285a5313c3fcf4ff13bd3ca",
#           "sequencer": "16DAB6450E18CA14"
#         }
#       }
#     }
#   ]
# }

logger = logging.getLogger(__name__)


def _process_object_created(base_uri, object_key):
    """Try to register new or update existing dataset entry if object created."""

    uuid, kind = _parse_obj_key(object_key)

    # We also need to update the database if the metadata has changed.
    # Here, we just brute-force attempt registration at every object write
    # as notifications may appear in arbitrary order. Another option might
    # be to look out for either the README.yml or the the 'dtool' object
    # of the respective UUID that finalizes creation of a dataset.
    dataset_uri = _reconstruct_uri(base_uri, object_key)

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
            logger.debug('DtoolCoreTypeError raised for dataset '
                         'with URI %s', dataset_uri)
            pass
    else:
        logger.info(("Creation of '%s' within '%s' does not constitute the "
                     "creation of a complete dataset or update of its metadata. "
                     "Ignored."), object_key, base_uri)

    return {}


def _process_object_removed(base_uri, object_key):
    """Notify the lookup server about deletion of an object."""
    # The only information that we get is the URL. We need to convert the URL
    # into the respective UUID of the dataset.

    # only delete dataset from index if the `dtool` object is deleted

    if object_key.endswith('/dtool'):  # somewhat dangerous if another item is named dtool
        uri = _reconstruct_uri(base_uri, object_key)
        uuid, kind = _parse_obj_key(object_key)
        assert kind == 'dtool'

        logger.info('Deleting dataset with URI {}'.format(uri))

        # Delete datasets with this URI
        sql_db.session.query(Dataset) \
            .filter(Dataset.uri == uri) \
            .delete()
        sql_db.session.commit()

        # Remove from Mongo database
        # https://pymongo.readthedocs.io/en/stable/api/pymongo/collection.html#pymongo.collection.Collection.delete_one
        mongo.db[MONGO_COLLECTION].delete_one({"uri": {"$eq": uri}})

    return {}


def _process_event(event_name, event_data):
    """"Delegate S3 notification event processing o correct handler."""
    response = {}
    # TODO: consider s3SchemaVersion

    if event_name in [*OBJECT_CREATED_EVENT_NAMES, *OBJECT_REMOVED_EVENT_NAMES]:
        try:
            bucket_name = event_data['bucket']['name']
        except KeyError as exc:
            logger.error(str(exc))
            abort(400)

        try:
            object_key = event_data['object']['key']
        except KeyError as exc:
            logger.error(str(exc))
            abort(400)

        # object keys are %xx-escaped, bucket names as well?
        logger.info("Received notification for raw bucket name '%s' and raw object key '%s'",
                    bucket_name, object_key)
        bucket_name = urllib.parse.unquote(bucket_name, encoding='utf-8', errors='replace')
        object_key = urllib.parse.unquote(object_key, encoding='utf-8', errors='replace')
        logger.info(
            "Received notification for de-escaped bucket name '%s' and de-escaped object key '%s'",
            bucket_name, object_key)

        # TODO: the same bucket name may exist at different locations wit different base URIS
        if bucket_name not in Config.BUCKET_TO_BASE_URI:
            logger.error("No base URI configured for bucket '%s'.", bucket_name)
            abort(400)

        base_uri = Config.BUCKET_TO_BASE_URI[bucket_name]

        if event_name in OBJECT_CREATED_EVENT_NAMES:
            logger.info("Object '%s' created within '%s'", object_key, base_uri)
            response = _process_object_created(base_uri, object_key)
        elif event_name in OBJECT_REMOVED_EVENT_NAMES:
            logger.info("Object '%s' removed from '%s'", object_key, base_uri)
            response = _process_object_removed(base_uri, object_key)

    else:
        logger.info("Event '%s' ignored.", event_name)

    return response


webhook_bp = Blueprint("webhook", __name__, url_prefix="/webhook")


# wildcard route,
# see https://flask.palletsprojects.com/en/2.0.x/patterns/singlepageapplications/
# strict_slashes=False matches '/notify' and '/notify/'
@webhook_bp.route('/notify', defaults={'path': ''}, methods=['POST'], strict_slashes=False)
@webhook_bp.route('/notify/<path:path>', methods=['POST'])
@filter_ips
def notify(path):
    """Notify the lookup server about creation, modification or deletion of a
    dataset."""

    json_content = None

    # special treatment for form data as submitted by NetApp Storage GRID
    if request.content_type.startswith('application/x-www-form-urlencoded'):
        logger.debug("Received 'application/x-www-form-urlencoded' content.")
        form = request.form
        logger.debug("Form:")
        _log_nested(logger.debug, form)
        if 'Message' in form:
            logger.debug("Try to parse 'Message' field of form as JSON.")
            try:
                json_content = json.loads(form['Message'])
                logger.debug("Succeeded to parse 'Message' field of form as JSON.")
            except:
                logger.warning("Failed to parse 'Message' field of form '%s' as JSON.", form['Message'])
    else: # general treatment, usually for 'application/json'
        json_content = request.get_json()

    logger.debug("Request JSON:")
    _log_nested(logger.debug, json_content)
    if json_content is None:
        logger.error("No JSON attached.")
        # health check: NetApp Storage GRID performs a health check post request,
        # but attaches content of type 'application/x-www-form-urlencoded', i.e.
        #  Action=Publish&Message=StorageGRID+Test+Message&TopicArn=urn%3Atest%3Asns%3Atest%3Atest%3Atest&Version=2010-03-31
        return {}

    logger.debug("Records:")
    _log_nested(logger.debug, json_content['Records'])

    try:
        event_name = json_content['Records'][0]['eventName']
    except KeyError:
        logger.error("No 'eventName' in 'Records''.")
        abort(400)

    try:
        event_data = json_content['Records'][0]['s3']
    except KeyError:
        logger.error("No 's3' in 'Records'.")
        abort(400)

    return jsonify(_process_event(event_name, event_data))


@webhook_bp.route("/config", methods=["GET"])
@jwt_required()
def plugin_config():
    """Return the JSON-serialized plugin configuration."""
    try:
        config = Config.to_dict()
    except AuthenticationError:
        abort(401)
    return jsonify(config)
