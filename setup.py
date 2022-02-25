import os
from setuptools import setup
from setuptools_scm import get_version
version = get_version(root='.', relative_to=__file__)

def local_scheme(version):
    """Skip the local version (eg. +xyz of 0.6.1.dev4+gdf99fe2)
    to be able to upload to Test PyPI"""
    return ""

url = "https://github.com/IMTEK-Simulation/dtool-lookup-server-notification-plugin"
readme = open('README.rst').read()

setup(
    name="dtool-lookup-server-notification-plugin",
    packages=["dtool_lookup_server_notification_plugin"],
    description="dtool lookup server plugin for receiving elastic-search update notifications",
    long_description=readme,
    author="Lars Pastewka",
    author_email="lars.pastewka@imtek.uni-freiburg.de",
    use_scm_version={
        "local_scheme": local_scheme,
        "root": '.',
        "relative_to": __file__,
        "write_to": os.path.join(
            "dtool_lookup_server_notification_plugin", "version.py"),
    },
    url=url,
    entry_points={
        'dtool_lookup_server.blueprints': [
            'dtool_lookup_server_notification_plugin_elasticsearch=dtool_lookup_server_notification_plugin.elasticsearch:elastic_search_bp',
            'dtool_lookup_server_notification_plugin_webhook=dtool_lookup_server_notification_plugin.webhook:webhook_bp',
        ],
    },
    setup_requires=['setuptools_scm'],
    install_requires=[
        "dtool-lookup-server>=0.17.2",
        "dtoolcore>=3.17.0",
        "dtool-s3>=0.13.0",
    ],
    download_url="{}/tarball/{}".format(url, version),
    license="MIT",
)
