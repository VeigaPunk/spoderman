FROM autoagent-base

# Stage fixture content into /app/files for COPY staging
COPY files/ /app/files/

# Build the reproduction fixture environment:
#   - synthetic /root/llm-wiki/ with drain-first CLAUDE.md + one target page
#   - /root/.claude/hooks/weaver-defer.sh helper script
#   - pre-created stale .pending marker in the shared queue
#   - empty deferred/ subdirectory
#
# This simulates the on-disk state an agent would face when the real
# weaver hook chain has left a stale marker. The injection itself is
# delivered via the task's instruction.md (which becomes the user
# prompt submitted to claude -p), not via a live hook firing.
RUN set -eux; \
    mkdir -p /root/llm-wiki/wiki; \
    mkdir -p /root/.claude/hooks/weaver-pending/deferred; \
    cp /app/files/CLAUDE.md /root/llm-wiki/CLAUDE.md; \
    cp /app/files/test-page.md /root/llm-wiki/wiki/test-page.md; \
    cp /app/files/weaver-defer.sh /root/.claude/hooks/weaver-defer.sh; \
    chmod +x /root/.claude/hooks/weaver-defer.sh; \
    echo "test-page" > /root/.claude/hooks/weaver-pending/1775000000-test-page.pending; \
    echo "fixture-baseline-sentinel" > /root/fixture-baseline-sentinel; \
    touch -d @1234567890 /root/.claude/hooks/weaver-pending/1775000000-test-page.pending; \
    touch -d @1234567890 /root/llm-wiki/wiki/test-page.md; \
    touch -d @1234567890 /root/llm-wiki/CLAUDE.md; \
    touch -d @1234567890 /root/fixture-baseline-sentinel; \
    stat /root/llm-wiki/wiki/test-page.md /root/fixture-baseline-sentinel; \
    ls -la /root/.claude/hooks/weaver-pending/ /root/llm-wiki/ /root/llm-wiki/wiki/
