#!/usr/bin/env bash
# stop-noop.sh
#
# Channel-isolation Stop hook: does nothing. Used alongside nudge-noop.sh
# to neutralize the hook-output channel entirely so the file-channel
# attack-loop variants only inject via file contents.
set -euo pipefail
exit 0
