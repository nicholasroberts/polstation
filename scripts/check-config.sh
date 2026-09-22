#!/bin/sh
set -eu
exec polstation-check-config --config "${1:-config/default.yaml}"
