"""
sentry.utils
~~~~~~~~~~~~

:copyright: (c) 2010 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

import datetime
import hashlib
import logging
import sys
import uuid
import warnings
from pprint import pformat
from types import ClassType, TypeType

import sentry
from sentry import app
from sentry.utils.encoding import force_unicode

FILTER_CACHE = None
def get_filters(from_cache=True):
    global FILTER_CACHE

    if FILTER_CACHE is None or not from_cache:
        filters = []
        for key, path in app.config['FILTERS']:
            module_name, class_name = path.rsplit('.', 1)
            try:
                module = __import__(module_name, {}, {}, class_name)
                handler = getattr(module, class_name)
            except Exception:
                logger = logging.getLogger('sentry.web.filters')
                logger.exception('Unable to import %s' % (path,))
                continue
            filters.append(handler(key))

        FILTER_CACHE = filters

    for f in FILTER_CACHE:
        yield f

def construct_checksum(level=logging.ERROR, class_name='', traceback='', message='', **kwargs):
    checksum = hashlib.md5(str(level))
    checksum.update(class_name or '')
    if traceback:
        traceback = '\n'.join(traceback.split('\n')[:-3])
    message = traceback or message
    if isinstance(message, unicode):
        message = message.encode('utf-8', 'replace')
    checksum.update(message)
    return checksum.hexdigest()

def varmap(func, var, context=None):
    if context is None:
        context = {}
    objid = id(var)
    if objid in context:
        return func('<...>')
    context[objid] = 1
    if isinstance(var, dict):
        ret = dict((k, varmap(func, v, context)) for k, v in var.iteritems())
    elif isinstance(var, (list, tuple)):
        ret = [varmap(func, f, context) for f in var]
    else:
        ret = func(var)
    del context[objid]
    return ret

def has_sentry_metadata(value):
    try:
        return callable(getattr(value, '__sentry__', None))
    except:
        return False

def transform(value, stack=[], context=None):
    # TODO: make this extendable
    # TODO: include some sane defaults, like UUID
    # TODO: dont coerce strings to unicode, leave them as strings
    if context is None:
        context = {}
    objid = id(value)
    if objid in context:
        return '<...>'
    context[objid] = 1
    if any(value is s for s in stack):
        ret = 'cycle'
    transform_rec = lambda o: transform(o, stack + [value], context)
    if isinstance(value, (tuple, list, set, frozenset)):
        ret = type(value)(transform_rec(o) for o in value)
    elif isinstance(value, uuid.UUID):
        ret = repr(value)
    elif isinstance(value, datetime.datetime):
        ret = value.strftime('%Y-%m-%dT%H:%M:%S.%f')
    elif isinstance(value, datetime.date):
        ret = value.strftime('%Y-%m-%d')
    elif isinstance(value, dict):
        ret = dict((k, transform_rec(v)) for k, v in value.iteritems())
    elif isinstance(value, unicode):
        ret = to_unicode(value)
    elif isinstance(value, str):
        try:
            ret = str(value)
        except:
            ret = to_unicode(value)
    elif not isinstance(value, (ClassType, TypeType)) and \
            has_sentry_metadata(value):
        ret = transform_rec(value.__sentry__())
    elif not isinstance(value, (int, bool)) and value is not None:
        # XXX: we could do transform(repr(value)) here
        ret = to_unicode(value)
    else:
        ret = value
    del context[objid]
    return ret

def to_unicode(value):
    try:
        value = unicode(force_unicode(value))
    except (UnicodeEncodeError, UnicodeDecodeError):
        value = '(Error decoding value)'
    except Exception: # in some cases we get a different exception
        try:
            value = str(repr(type(value)))
        except Exception:
            value = '(Error decoding value)'
    return value

class _Missing(object):

    def __repr__(self):
        return 'no value'

    def __reduce__(self):
        return '_missing'

_missing = _Missing()

class cached_property(object):
    # This is borrowed from werkzeug : http://bytebucket.org/mitsuhiko/werkzeug-main
    """A decorator that converts a function into a lazy property.  The
    function wrapped is called the first time to retrieve the result
    and then that calculated result is used the next time you access
    the value::

        class Foo(object):

            @cached_property
            def foo(self):
                # calculate something important here
                return 42

    The class has to have a `__dict__` in order for this property to
    work.

    .. versionchanged:: 0.6
       the `writeable` attribute and parameter was deprecated.  If a
       cached property is writeable or not has to be documented now.
       For performance reasons the implementation does not honor the
       writeable setting and will always make the property writeable.
    """

    # implementation detail: this property is implemented as non-data
    # descriptor.  non-data descriptors are only invoked if there is
    # no entry with the same name in the instance's __dict__.
    # this allows us to completely get rid of the access function call
    # overhead.  If one choses to invoke __get__ by hand the property
    # will still work as expected because the lookup logic is replicated
    # in __get__ for manual invocation.

    def __init__(self, func, name=None, doc=None, writeable=False):
        if writeable:
            warnings.warn(DeprecationWarning('the writeable argument to the '
                                    'cached property is a noop since 0.6 '
                                    'because the property is writeable '
                                    'by default for performance reasons'))

        self.__name__ = name or func.__name__
        self.__module__ = func.__module__
        self.__doc__ = doc or func.__doc__
        self.func = func

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        value = obj.__dict__.get(self.__name__, _missing)
        if value is _missing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value

def get_versions(module_list=[]):
    # TODO:
    ext_module_list = set()
    for m in module_list:
        parts = m.split('.')
        ext_module_list.update('.'.join(parts[:idx]) for idx in xrange(1, len(parts)+1))

    versions = {}
    for module_name in ext_module_list:
        __import__(module_name)
        app = sys.modules[module_name]
        if hasattr(app, 'get_version'):
            get_version = app.get_version
            if callable(get_version):
                version = get_version()
            else:
                version = get_version
        elif hasattr(app, 'VERSION'):
            version = app.VERSION
        elif hasattr(app, '__version__'):
            version = app.__version__
        else:
            continue
        if isinstance(version, (list, tuple)):
            version = '.'.join(str(o) for o in version)
        versions[module_name] = version
    return versions

def shorten(var):
    var = transform(var)
    if isinstance(var, basestring) and len(var) > sentry.app.config['MAX_LENGTH_STRING']:
        var = var[:sentry.app.config['MAX_LENGTH_STRING']] + '...'
    elif isinstance(var, (list, tuple, set, frozenset)) and len(var) > sentry.app.config['MAX_LENGTH_LIST']:
        # TODO: we should write a real API for storing some metadata with vars when
        # we get around to doing ref storage
        # TODO: when we finish the above, we should also implement this for dicts
        var = list(var)[:sentry.app.config['MAX_LENGTH_LIST']] + ['...', '(%d more elements)' % (len(var) - sentry.app.config['MAX_LENGTH_LIST'],)]
    return var

def is_float(var):
    try:
        float(var)
    except ValueError:
        return False
    return True

class MockRequest(object):
    GET = {}
    POST = {}
    META = {}
    COOKIES = {}
    FILES = {}
    raw_post_data = ''
    url = ''
    
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    
    def __repr__(self):
        # Since this is called as part of error handling, we need to be very
        # robust against potentially malformed input.
        try:
            get = pformat(self.GET)
        except:
            get = '<could not parse>'
        try:
            post = pformat(self.POST)
        except:
            post = '<could not parse>'
        try:
            cookies = pformat(self.COOKIES)
        except:
            cookies = '<could not parse>'
        try:
            meta = pformat(self.META)
        except:
            meta = '<could not parse>'
        return '<Request\nGET:%s,\nPOST:%s,\nCOOKIES:%s,\nMETA:%s>' % \
            (get, post, cookies, meta)

    def build_absolute_uri(self): return self.url
