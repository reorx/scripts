# Workload-aware process CPU alerts

The monitoring stack lives in `~/Documents/macos-monitoring`. Its documents are the source of truth for commands, fields, thresholds and the deploy mechanics; this file only adds the judgment and the order of work. Read first:

- `AGENTS.md` — stack layout, services, and the alert-pipeline invariants that must not be "optimized" away.
- `kb/docs/process-rules.md` — the `process-rules.yaml` policy file, its generator `scripts/process_rules.py`, the current thresholds, and the test, deploy and rollback commands.
- `kb/notes/parallels-process-context.md` — verified facts about the Parallels VM behind `prl_vm_app`.
- `scripts/README.md` — replay and verification scripts, including `replay_rule.py`.
- `kb/docs/hermes-alerts.md` — the AI triage path that receives the policy as alert metadata.

## 1. Establish identity, units, and expected work

Resolve the alerted PID with `ps -p <pid> -ww -o pid,ppid,%cpu,etime,comm` before changing policy. Distinguish recent `ps` CPU, sampled CPU, rolling averages and whole-machine utilization; a lower current sample does not invalidate a rolling-average alert.

For Parallels, verify that `prl_vm_app` belongs to the Parallels application bundle, and inspect `prlctl list -a -i` to find the running VM rather than an invalid or stale registration. vCPU counts with `auto=on` are observations, not limits, and host helper threads add CPU on top, so guest vCPUs × 100 is not a hard ceiling for the process.

Record expected workload context in the monitoring project's knowledge base. Don't encode an old PID, a one-time user activity or a proposed threshold as a standing exemption, and never stop or restart the user's VM because it crossed a desktop-process threshold.

## 2. Change the policy through the generator

Edit only `process-rules.yaml`, then preview with the generator; never hand-edit the generated CPU region of `grafana/provisioning/alerting/rules.yaml`, and don't introduce a second policy store. Read current values from the configuration instead of copying numbers into this skill.

If the generator itself has to change, keep what it guarantees today: overridden names are excluded from the default selector (otherwise the original nuisance alert still fires), same-name processes are still evaluated per PID, unknown keys and malformed values are rejected, and the matched policy travels as generated labels and annotations into the Hermes evidence, with the averaging denominator computed from the actual window and collector interval. Machine-wide saturation, memory and collector alerts, existing pause states and the AI budgets stay untouched.

## 3. Test and replay before touching live rules

Run the project's test commands listed in `kb/docs/process-rules.md`. Compare the old and proposed expressions with `scripts/replay_rule.py` over retained history, keeping windows and `for` durations aligned with each candidate. Store replay output in the task's `tmp/` folder and describe it as historical behavior, not proof that future faults cannot be missed.

Don't generate CPU load or trigger an LLM session just to show that policy metadata reaches the collector; a read-only probe of the deployed rule against live metrics is enough for that narrower claim. Label any simulation as a fixture.

## 4. Deploy and read back

Deploy only after the user approves the policy, with the generator's `--deploy` followed by `--check`. It backs up, replaces only the generated region and hot-reloads Grafana's alert provisioning; don't restart Grafana instead.

Then read back expressions, thresholds, `for`, labels, annotations and pause state, and confirm the rules have actually evaluated with healthy status. Check that `cd cli && uv run macmon.py alerts` shows the new thresholds. If `scripts/hermes_alert_filter.py` changed, update its deployed copy at `~/.hermes/scripts/monitoring_alert_filter.py` atomically — editing the repo file alone does not change what runs.

Compare unrelated rules semantically. A reload changes the server-maintained `updated` field on every provisioned rule; that alone is not evidence their definitions changed.

## 5. Retire and roll back through the generator

Grafana file provisioning only upserts, so deleting a rule from YAML leaves the live rule running. The generator retires removed policies with an explicit `deleteRules` block and restores the previous rules on a failed read-back. Don't bypass it by copying an old `rules.yaml`. If it refuses because an unfinished `deleteRules` block exists, or reports that a restore failed, stop and report the incomplete state rather than claiming the system is back to normal.
