"""Test conversion of URL to base URI and UUID"""

from dtool_lookup_server_notification_plugin import Config, _parse_objpath


def test_parse_objpath():
    my_base_uri = 'ecs://frct-simdata'
    Config.BUCKET_TO_BASE_URI = {'frct-simdata': my_base_uri}

    base_uri, uuid, kind = _parse_objpath(
        'frct-simdata_u/lp1029/6ea79d31-f100-486a-9e78-c5b609cb35de/dtool')
    assert base_uri == my_base_uri
    assert uuid == '6ea79d31-f100-486a-9e78-c5b609cb35de'
    assert kind == 'dtool'

    base_uri, uuid, kind = _parse_objpath(
        'frct-simdata_6ea79d31-f100-486a-9e78-c5b609cb35de/dtool')
    assert base_uri == my_base_uri
    assert uuid == '6ea79d31-f100-486a-9e78-c5b609cb35de'
    assert kind == 'dtool'

    base_uri, uuid, kind = _parse_objpath(
        'frct-simdata_u/lp1029/6ea79d31-f100-486a-9e78-c5b609cb35de/README.yml')
    assert base_uri == my_base_uri
    assert uuid == '6ea79d31-f100-486a-9e78-c5b609cb35de'
    assert kind == 'README.yml'

    base_uri, uuid, kind = _parse_objpath(
        'frct-simdata_u/as1412/800f1b37-4bff-4013-805d-1a1ff61de1f2/data/18a3e253316409e313493b853f42f3f95243c404')
    assert base_uri == my_base_uri
    assert uuid == '800f1b37-4bff-4013-805d-1a1ff61de1f2'
    assert kind == 'data'

    base_uri, uuid, kind = _parse_objpath(
        'frct-simdata_u/lp1029/a7e3405b-5efa-49ca-95d3-4068190d50a2/annotations/test_annotation.json')
    assert base_uri == my_base_uri
    assert uuid == 'a7e3405b-5efa-49ca-95d3-4068190d50a2'
    assert kind == 'annotations'

    base_uri, uuid, kind = _parse_objpath(
        'frct-simdata_dtool-f8784b1e-ba60-4200-baa7-397856fe83ec')
    assert base_uri == my_base_uri
    assert uuid == 'f8784b1e-ba60-4200-baa7-397856fe83ec'
    assert kind == '__REGISTRATION_KEY__'