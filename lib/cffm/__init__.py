from importlib.metadata import PackageNotFoundError, version

try:
    # Change here if project is renamed and does not equal the package name
    dist_name = __name__
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError


from cffm.field import MISSING, field, property_field, Ref
from cffm.config import config, section, sections_from_entrypoints
from cffm.multi import MultiSourceConfig
from cffm.source import *
