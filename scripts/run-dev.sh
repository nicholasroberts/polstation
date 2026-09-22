#!/bin/sh
set -eu
# Run the dashboard separately with polstation-dashboard.
exec polstation-acquisition --config "${1:-config/default.yaml}"
