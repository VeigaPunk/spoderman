#!/usr/bin/env bash
# nudge-noop.sh
#
# Channel-isolation nudge: does nothing. Emits no output, takes no action.
# Used by the file-channel attack-loop variants to isolate the file-content
# injection effect from the hook-channel baseline.
#
# Shape matches the original weaver-drain-nudge.sh so the hook chain still
# fires the script, it just exits clean with no stdout. The stop-hook
# subprocess will return an empty <system-reminder> block (or no block at
# all), so no drain instructions reach the agent through this channel.
set -euo pipefail
exit 0
