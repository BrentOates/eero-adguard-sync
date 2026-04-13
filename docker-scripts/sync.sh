#!/bin/sh

# EAG_SYNC_FLAGS is supported for backwards compatibility (e.g. "-y -d")
# Prefer individual env vars (EAG_CONFIRM, EAG_DELETE, etc.) for new deployments.
eag-sync sync ${EAG_SYNC_FLAGS:-}
