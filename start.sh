#!/usr/bin/env bash
# Convenience alias — same as ./dev.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dev.sh" "$@"
