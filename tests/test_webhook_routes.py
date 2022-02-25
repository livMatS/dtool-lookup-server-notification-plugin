"""Test the /webhook/notify blueprint route."""
import ipaddress
import json
import os
import shutil
import urllib.parse

import dtoolcore
import yaml

from dtoolcore import ProtoDataSet, generate_admin_metadata
from dtoolcore import DataSet
from dtoolcore.utils import generate_identifier, sanitise_uri
from dtoolcore.storagebroker import DiskStorageBroker

from dtool_lookup_server.utils import (
    get_readme_from_uri_by_user,
    list_datasets_by_user,
    register_base_uri,
    update_permissions,
)
from dtool_lookup_server_notification_plugin import Config

from . import (
    access_restriction,
    immuttable_dataset_uri,
    tmp_app_with_users,
    tmp_dir_fixture,
    request_json,
    TEST_SAMPLE_DATA
) # NOQA


def test_webhook_notify_route(tmp_app_with_users, tmp_dir_fixture,
                              request_json, immuttable_dataset_uri):  # NOQA
    bucket_name = 'bucket'

    # Add local directory as base URI and assign URI to the bucket
    base_uri = sanitise_uri(tmp_dir_fixture)
    register_base_uri(base_uri)
    update_permissions({
        'base_uri': base_uri,
        'users_with_search_permissions': ['snow-white'],
        'users_with_register_permissions': ['snow-white'],
    })
    Config.BUCKET_TO_BASE_URI[bucket_name] = base_uri

    # Read in a dataset
    dataset = DataSet.from_uri(immuttable_dataset_uri)
    uuid = dataset.uuid
    name = dataset.name

    expected_identifier = generate_identifier('simple_text_file.txt')
    assert expected_identifier in dataset.identifiers
    assert len(dataset.identifiers) == 1

    # dataset acrobatics, need to get rid of all that
    dtoolcore.copy(immuttable_dataset_uri, tmp_dir_fixture)

    dest_uri = sanitise_uri('/'.join((tmp_dir_fixture, name)))
    dataset = DataSet.from_uri(dest_uri)
    readme = 'abc: def'
    dataset.put_readme(readme)

    # modify mock event to match our temporary dataset
    request_json['Records'][0]['eventName'] = 's3:ObjectCreated:Put'
    request_json['Records'][0]['s3']['bucket']['name'] = bucket_name
    # notification plugin will try to register dataset when README.yml created or changed
    request_json['Records'][0]['s3']['object']['key'] = urllib.parse.quote(f'{uuid}/README.yml')

    # Tell plugin that dataset has been created
    r = tmp_app_with_users.post("/webhook/notify", json=request_json)
    assert r.status_code == 200

    # Check that dataset has actually been registered
    datasets = list_datasets_by_user('snow-white')
    assert len(datasets) == 1
    assert datasets[0]['base_uri'] == base_uri
    assert datasets[0]['uri'] == dest_uri
    assert datasets[0]['uuid'] == uuid # admin_metadata['uuid']
    assert datasets[0]['name'] == name

    # Check README
    check_readme = get_readme_from_uri_by_user('snow-white', dest_uri)
    assert check_readme == yaml.safe_load(readme)

    # Update README
    new_readme = 'ghi: jkl'
    dataset.put_readme(new_readme)

    # Notify plugin about updated name
    r = tmp_app_with_users.post("/webhook/notify", json=request_json)
    assert r.status_code == 200

    # Check dataset
    datasets = list_datasets_by_user('snow-white')
    assert len(datasets) == 1
    assert datasets[0]['base_uri'] == base_uri
    assert datasets[0]['uri'] == dest_uri
    assert datasets[0]['uuid'] == uuid
    assert datasets[0]['name'] == name

    # Check that README has actually been changed
    check_readme = get_readme_from_uri_by_user('snow-white', dest_uri)
    assert check_readme == yaml.safe_load(new_readme)

    # notification plugin will try to remove dataset from index
    # # when the dtool object is deleted
    request_json['Records'][0]['eventName'] = 's3:ObjectRemoved:Delete'
    request_json['Records'][0]['s3']['object']['key'] = urllib.parse.quote(f'{uuid}/dtool')
    r = tmp_app_with_users.post("/webhook/notify", json=request_json)
    assert r.status_code == 200

    # Check that dataset has been deleted
    datasets = list_datasets_by_user('snow-white')
    assert len(datasets) == 0


def test_webhook_access_restriction(tmp_app_with_users, request_json, access_restriction):
    # Remote address in test is 127.0.0.1
    r = tmp_app_with_users.post(
        "/webhook/notify", json=request_json
    )
    assert r.status_code == 403  # Forbidden
