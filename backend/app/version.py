"""Single source of the application version.

Used by the FastAPI metadata, the upgrade pre-check and backup manifests so a
backup can always be matched to the exact software version that produced it.
"""

APP_VERSION = '1.9.0'
