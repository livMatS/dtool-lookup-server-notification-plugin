"""Test the /scaffolding/config blueprint route."""
import ipaddress
import os
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

from . import tmp_app_with_users, tmp_dir_fixture, TEST_SAMPLE_DATA  # NOQA
from . import snowwhite_token

def test_notify_route(tmp_app_with_users, tmp_dir_fixture):  # NOQA
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

    # Create test dataset
    name = "my_dataset"
    admin_metadata = generate_admin_metadata(name)
    dest_uri = DiskStorageBroker.generate_uri(
        name=name,
        uuid=admin_metadata["uuid"],
        base_uri=tmp_dir_fixture)

    sample_data_path = os.path.join(TEST_SAMPLE_DATA)
    local_file_path = os.path.join(sample_data_path, 'tiny.png')

    # Create a minimal dataset
    proto_dataset = ProtoDataSet(
        uri=dest_uri,
        admin_metadata=admin_metadata,
        config_path=None)
    proto_dataset.create()
    readme = 'abc: def'
    proto_dataset.put_readme(readme)
    proto_dataset.put_item(local_file_path, 'tiny.png')

    proto_dataset.freeze()

    # Read in a dataset
    dataset = DataSet.from_uri(dest_uri)

    expected_identifier = generate_identifier('tiny.png')
    assert expected_identifier in dataset.identifiers
    assert len(dataset.identifiers) == 1

    # Tell plugin that dataset has been created
    r = tmp_app_with_users.post(
        "/elastic-search/notify/all/{}".format(name),
        json={'bucket': bucket_name, 'metadata': dataset._admin_metadata},
    )
    assert r.status_code == 200

    # Check that dataset has actually been registered
    datasets = list_datasets_by_user('snow-white')
    assert len(datasets) == 1
    assert datasets[0]['base_uri'] == base_uri
    assert datasets[0]['uri'] == dest_uri
    assert datasets[0]['uuid'] == admin_metadata['uuid']
    assert datasets[0]['name'] == name

    # Check README
    check_readme = get_readme_from_uri_by_user('snow-white', dest_uri)
    assert check_readme == yaml.load(readme)

    # Update README
    new_readme = 'ghi: jkl'
    dataset.put_readme(new_readme)

    # Notify plugin about updated name
    r = tmp_app_with_users.post(
        "/elastic-search/notify/all/{}".format(name),
        json={'bucket': bucket_name, 'metadata': dataset._admin_metadata},
    )
    assert r.status_code == 200

    # Check dataset
    datasets = list_datasets_by_user('snow-white')
    assert len(datasets) == 1
    assert datasets[0]['base_uri'] == base_uri
    assert datasets[0]['uri'] == dest_uri
    assert datasets[0]['uuid'] == admin_metadata['uuid']
    assert datasets[0]['name'] == name

    # Check that README has actually been changed
    check_readme = get_readme_from_uri_by_user('snow-white', dest_uri)
    assert check_readme == yaml.load(new_readme)

    # Tell plugin that dataset has been deleted
    r = tmp_app_with_users.delete(
        "/elastic-search/notify/all/{}_{}/dtool".format(bucket_name, admin_metadata['uuid'])
    )
    assert r.status_code == 200

    # Check that dataset has been deleted
    datasets = list_datasets_by_user('snow-white')
    assert len(datasets) == 0


def test_access_restriction(tmp_app_with_users):
    # Remote address in test is 127.0.0.1
    Config.ALLOW_ACCESS_FROM = ipaddress.ip_network("1.2.3.4")

    r = tmp_app_with_users.post(
        "/elastic-search/notify/all/test_access_restriction"
    )
    assert r.status_code == 403  # Forbidden

    r = tmp_app_with_users.delete(
        "/elastic-search/notify/all/test_access_restriction"
    )
    assert r.status_code == 403  # Forbidden
