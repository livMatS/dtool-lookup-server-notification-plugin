"""Test the /scaffolding/config blueprint route."""

import json
import dtool_lookup_server_notification_plugin

from . import tmp_app_with_users  # NOQA
from . import snowwhite_token

def test_config_info_route(tmp_app_with_users):  # NOQA

    headers = dict(Authorization="Bearer " + snowwhite_token)
    r = tmp_app_with_users.get(
        "/elastic-search/config",
        headers=headers,
    )
    assert r.status_code == 200

    expected_content = {
        "allow_access_from": "0.0.0.0/0",
        "bucket_to_base_uri": {"bucket": "s3://bucket"},
        "version": dtool_lookup_server_notification_plugin.__version__}

    response = json.loads(r.data.decode("utf-8"))
    assert response == expected_content


