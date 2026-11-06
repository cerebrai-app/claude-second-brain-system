---
name: pending
description: Review the deferred Claude-action proposals that were queued by sync, and approve, edit or reject them. Use when the user runs /brain:pending or asks about pending approvals.
argument-hint: "[reject-all] [--impl <id>]"
disable-model-invocation: true
---

# /brain:pending

Read the `core` skill and the automation reference first.

1. Run `brainctl pending list --prune` (it drops expired entries and reports each remaining one as `fresh` or `stale`; file shape: the automation reference, Pending entry file), grouped by `<type>/<impl-id>`, newest last. Report the count. Drop entries older than the expiry (default 14 days) with a note.
2. For each entry the user wants to review: **re-evaluate against current state first**. Re-read the item; if it changed so the proposal no longer applies, regenerate the proposal or drop the entry with a note. Never apply a stale proposal.
3. Show the rule id, the instruction, the triggering event, the exact operations as diffs, and the rationale. The user can **approve**, **edit** (re-validate), or **reject** (logged; the file is removed).
4. After the user approves, `brainctl pending apply <id>` applies the operations exactly as shown (pass edited operations with `--json '{"operations": [...]}'`), refuses a stale entry, deletes the file and logs `approved-applied`. `brainctl pending reject <id>` rejects (logged). `reject-all` rejects every listed entry after one confirmation.

There is no "always allow". Approval is always per proposal.
