<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Automation Path

This skill should eventually become automated workflows:
1. Phases 1-4: Automated workflow triggered by webhook (TAM check + research + normalization)
2. Phase 6: AI generation nodes + code nodes (variable generation at scale)
3. Phase 7: Validation workflow with Slack/alert on failures
4. Phase 11: User approves via Slack button or similar, workflow activates campaigns
5. Phase 13: Automated weekly signal performance reports feeding back into targeting

### Every unattended job needs a circuit breaker (NON-NEGOTIABLE)

The moment a phase runs without someone watching, its failure mode changes. Supervised, a crash is an inconvenience. Unsupervised with a default restart policy, a crash becomes a loop.

**One crash can be transient. A second consecutive crash means stop everything. There is no third retry.**

1. Count consecutive failures in storage that survives a restart - a database row or a KV flag. Never a variable in the process, which resets to zero on every restart and makes the counter useless precisely when you need it.
2. Check the counter before the risky operation, at startup. If tripped, exit cleanly with a success code and log loudly - a crash-on-startup is itself a restartable event.
3. Set the platform's restart policy to never, or at most one retry. The common default is ten.
4. Clearing the breaker requires a human. Never auto-clear after N hours.

**Why the second crash is the line:** auth failures, rate limits and spend all compound on retry. Each restart makes the situation worse rather than better. Ours retried a third-party login five times in ninety seconds and got the account session invalidated. The account survived. A less forgiving service would have locked it permanently or drained the budget.

This applies to every scheduled thing you build: cron workers, AI generation loops, the email waterfall, bulk pushes, anything on a timer.
