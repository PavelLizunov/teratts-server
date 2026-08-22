# Prompt for a Trajectory-enabled remediation chat

Use the complete prompt from the approving project conversation. Required operating shape:

1. `AUDIT` is read-only and ends with evidence-labelled findings, drift/parity matrices and the exact line: `AUDIT завершён. Изменения не применялись. Ожидаю Review Gate.`
2. `REVIEW GATE` produces a one-screen Spec v2 and waits for explicit approval.
3. `APPLY` may update AGENTS.md, relevant skills, SDD templates, deployment/checklist docs and focused tests only after approval.

Mandatory audit themes: multi-agent orchestration for long objectives; compaction-resistant phase artifacts; Linux-first service policy; a decision gate for unspecified runtime topology; Spec amendment on architecture drift; exact-SHA deployment; no restart of a serving host from its active session; DSH design-system primitives; upstream/RUAccent parity; browser acceptance; truthful evidence labels; resource/security review; and anti-overfitting of global rules to a single incident.

The target chat must require root-cause evidence, change boundaries, verification and rollback; it must not declare production readiness while required browser, parity, security, downloader or exact-deployment checks remain unverified.

The full copy-ready prompt was also emitted in this project conversation and should be pasted verbatim when starting that dedicated Trajectory remediation chat.
