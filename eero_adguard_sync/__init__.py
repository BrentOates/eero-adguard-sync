from importlib.metadata import version, PackageNotFoundError


try:
    VERSION = version("eero-adguard-sync")
except PackageNotFoundError:
    VERSION = "__missing__"
