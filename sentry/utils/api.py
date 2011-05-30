from sentry import VERSION

import binascii
import hashlib
import hmac

def get_auth_header(signature, timestamp, client, nonce):
    return 'Sentry sentry_signature=%s, sentry_timestamp=%s, sentry_nonce=%s, sentry_client=%s' % (
        signature,
        timestamp,
        nonce,
        VERSION,
    )

def parse_auth_header(header):
    return dict(map(lambda x: x.strip().split('='), header.split(' ', 1)[1].split(',')))

def get_mac_signature(key, data):
    """
    Returns BASE64 ( HMAC-SHA1 (key, data) )
    """
    hashed = hmac.new(str(key), data, hashlib.sha1)
    return binascii.b2a_base64(hashed.digest())[:-1]