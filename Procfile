# ONE definition of how the app boots: start.sh. This file previously carried a second,
# divergent gunicorn invocation (`--workers 1 --log-level debug`) — the exact single-sync-worker
# config that made pages take ~10 s (see start.sh, prod-perf-audit 2026-09-05). It was dead as
# long as DO used the run command, but any fallback to buildpack detection would have silently
# reverted the fix. Delegate instead of duplicating.
web: ./start.sh
