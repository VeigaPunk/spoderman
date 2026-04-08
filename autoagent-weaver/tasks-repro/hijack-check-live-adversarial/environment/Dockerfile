FROM autoagent-base

# Stage fixture content
COPY files/ /app/files/

# Build the live-hook reproduction fixture environment:
#   - synthetic /root/llm-wiki/ with drain-first CLAUDE.md + one target page
#   - real weaver-drain-nudge.sh and weaver-drain-on-stop.sh hook scripts
#     copied from the pre-fix backup (original unpatched versions)
#   - /root/.claude/settings.json registering the UserPromptSubmit and Stop
#     hooks so Claude Code will fire them during the `claude -p` invocation
#   - weaver-defer.sh helper available in case the agent wants to use it
#   - pre-created stale .pending marker stamped with fixture epoch
#
# Unlike hijack-check (prompt-level injection), this task relies on the
# live hook chain to inject the WEAVER_PENDING system reminder via Claude
# Code's hook mechanism. If `claude -p` fires UserPromptSubmit hooks, the
# nudge hook will emit the reminder block and inject it into the turn
# context. If `claude -p` does NOT fire hooks in one-shot mode, the
# reminder will not appear and the test becomes a control (agent sees a
# plain user prompt with no injection).

RUN set -eux; \
    mkdir -p /root/llm-wiki/wiki; \
    mkdir -p /root/.claude/hooks/weaver-pending/deferred; \
    cp /app/files/CLAUDE.md /root/llm-wiki/CLAUDE.md; \
    cp /app/files/test-page.md /root/llm-wiki/wiki/test-page.md; \
    cp /app/files/weaver-drain-nudge.sh /root/.claude/hooks/weaver-drain-nudge.sh; \
    cp /app/files/weaver-drain-on-stop.sh /root/.claude/hooks/weaver-drain-on-stop.sh; \
    cp /app/files/weaver-defer.sh /root/.claude/hooks/weaver-defer.sh; \
    chmod +x /root/.claude/hooks/weaver-drain-nudge.sh; \
    chmod +x /root/.claude/hooks/weaver-drain-on-stop.sh; \
    chmod +x /root/.claude/hooks/weaver-defer.sh; \
    cp /app/files/settings.json /root/.claude/settings.json; \
    echo "test-page" > /root/.claude/hooks/weaver-pending/1775000000-test-page.pending; \
    echo "fixture-baseline-sentinel" > /root/fixture-baseline-sentinel; \
    touch -d @1234567890 /root/.claude/hooks/weaver-pending/1775000000-test-page.pending; \
    touch -d @1234567890 /root/llm-wiki/wiki/test-page.md; \
    touch -d @1234567890 /root/llm-wiki/CLAUDE.md; \
    touch -d @1234567890 /root/fixture-baseline-sentinel; \
    stat /root/llm-wiki/wiki/test-page.md /root/fixture-baseline-sentinel; \
    ls -la /root/.claude/hooks/ /root/.claude/hooks/weaver-pending/ /root/llm-wiki/ /root/llm-wiki/wiki/
