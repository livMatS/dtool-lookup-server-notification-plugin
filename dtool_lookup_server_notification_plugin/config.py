import ipaddress
import json
import os

from . import __version__

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