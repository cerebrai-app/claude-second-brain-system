# 04 — Sorts and Filters

Status: **Draft** · Depends on: [01 — Core Data Model](01-core-data-model.md), [03 — Storage Contract](03-storage-contract.md) · Used by: [05 — Automation](05-automation.md)

## Goal

Let an implementation define its own **sorts** and **filters** as plain-English rules that Claude interprets (decision in doc 01), while
keeping results as **predictable, auditable and cheap** as a natural-language rule can be. This doc specifies how a rule is evaluated,
what Claude sees and returns, and the mechanisms that make repeated evaluation stable.

## Terms

- **Filter** — a named natural-language description of which items qualify.
- **Sort** — a named natural-language description of how items are ordered.
- **View** — a filter plus an optional sort, used together (e.g. by `surface`, doc 05, or when the user asks "show actionable-today by due date").
- **Evaluation** — one run of a filter and/or sort over a set of items.

## Definition

In the implementation definition (doc 01):

```yaml
filters:
  actionable-today:
    rule: "Open tasks that are not blocked and are either undated or due today or earlier."
    scope: { fields_eq: { status: open } }     # optional structural pre-filter (see Pipeline)
    uses_body: false                            # default; set true if the rule needs the item body
    interpretation:                             # optional; compiled + approved once (see Pinned interpretation)
      rule_hash: "sha256:..."                   # hash of `rule`; if the text changes this is stale
      predicate: { and: [ { eq: [field.status, "open"] }, { not: { relation_any: [blocked_by, { eq: [field.status, "open"] }] } },
                          { or: [ { missing: field.due }, { lte: [field.due, today] } ] } ] }
    examples:                                   # optional; used as regression tests and context
      - item: { fields: { status: open, due: 2026-11-02 }, relations: { blocked_by: [] } }
        include: true
      - item: { fields: { status: open, due: 2026-11-20 } }
        include: false
sorts:
  due-then-priority:
    rule: "Soonest due date first; undated tasks last; ties broken by higher priority first."
    keys:                                       # optional, see Sort evaluation
      - { name: due,      type: date,   direction: asc,  missing: last }
      - { name: priority, type: enum,   order: [high, med, low] }
```

A rule is a short, self-contained English description. Guidance for authors (to be included in the plugin docs): name the fields used, state how
missing values behave, state how ties break, and avoid relative terms without a reference (say "due today or earlier", not "soon").

## Pipeline

1. **Resolve.** Look up the rule(s) by name in the implementation definition; compute the **scope** = the implementation's items, narrowed by `scope`.
2. **Pre-filter (structural, deterministic).** Translate `scope` into a storage `query` (doc 03: `types`, `impls`, `fields_eq`, `relations_include`,
   `updated_since`, `include_archived`) and page through `list`. The `scope` is **author-supplied**, never inferred by Claude from the rule text, so a
   misread rule cannot silently drop candidates. Adapters apply what they honor; the plugin applies the rest client-side. Archived items are
   excluded unless the view says otherwise.
3. **Batch.** Split the candidates into batches of at most `max_items_per_call` (default **20**). Small result sets are one call.
4. **Evaluate (Claude, read-only).** Each batch is judged by Claude with no write tools (it cannot change anything while evaluating).
5. **Validate.** The plugin checks Claude's output against the strict schema below. Invalid output is retried once with the validation error;
   a second failure aborts the evaluation visibly. Partial results are never returned as if complete.
6. **Merge and order.** The plugin merges batch results and performs the final ordering deterministically.
7. **Return** refs (and a short explanation), not modified items. Callers read full items through storage as needed.

## What Claude receives

- The rule text (and `examples`), the evaluation kind (filter / sort / both).
- For each candidate: `ref`, `type`, `impl`, `fields`, `relations` (as refs), `created`, `updated`, `archive`. **Not the body**, unless `uses_body: true`.
- **Evaluation context:** current date and time with timezone (from the user's settings), so "today" is unambiguous; vault `name`.
- Related items **only if the rule requires them** and the definition lists the needed relations in `follow: [blocked_by]`; the plugin resolves those refs
  (doc 03) and attaches a minimal view of each (`ref`, status/relevant fields). Claude cannot fetch more on its own.

## What Claude returns

### Filter

```json
{ "kind": "filter",
  "results": [ { "ref": "task:01J...", "include": true, "reason": "Due 2026-11-02, not blocked." } ],
  "assumptions": [ "Treated undated tasks as qualifying." ],
  "time_dependent": true,
  "ambiguity": null }
```

Every input ref appears **exactly once**. No invented refs, no omissions, no duplicates. `reason` is mandatory (one short sentence) and is shown on request.

### Sort evaluation (key extraction)

For anything beyond a handful of items the final order is **not** decided by Claude's overall judgment. Claude instead returns a **sort key per item**
that the plugin sorts deterministically:

```json
{ "kind": "sort",
  "key_schema": [ { "name": "due", "type": "date", "direction": "asc", "missing": "last" },
                  { "name": "priority", "type": "int", "direction": "desc" } ],
  "keys": { "task:01J...": { "due": "2026-11-02", "priority": 2 }, "task:01K...": { "due": null, "priority": 1 } },
  "assumptions": [], "time_dependent": false, "ambiguity": null }
```

- If the definition provides `keys`, Claude must use that schema (so the interpretation is pinned by the author). If not, Claude proposes
  `key_schema` on the first evaluation and the plugin **shows it to the user and stores it** with the rule (`keys`) once approved; later evaluations reuse it.
- The plugin sorts with a **stable sort** over the keys (missing handled per `missing`), and breaks remaining ties by `created`, then `ref`. This makes the order
  identical for identical keys, regardless of batching.
- For lists of ≤ `direct_sort_max` (default **10**) items, Claude may return an `order` array directly if the rule is inherently holistic ("most important first"); the plugin validates it is a permutation.

### Ambiguity

If the rule cannot be applied confidently (a field it names does not exist, two readings give different results, ...), Claude returns `ambiguity` with a
short question instead of guessing. Interactive: the plugin asks the user once, and offers to **rewrite the rule** (edit the definition) so the question is answered permanently.
Unattended: the evaluation fails and is logged.

## Reproducibility

Natural-language rules can drift between runs. The mechanisms, in order of strength:

1. **Deterministic parts stay deterministic:** pre-filter, validation, merging, tie-breaks and the final sort are code. Only per-item judgment and key extraction are model-based.
2. **Pinned key schemas** (`keys`) for sorts, stored in the definition.
3. **Examples as tests:** when a rule's text or `examples` change, the plugin evaluates the examples and reports mismatches before the rule is used. Examples are also supplied as few-shot context.
4. **Result cache:** results are cached by `(implementation, rule name, rule-text hash, set of (ref, revision) of the candidates, current date if `time_dependent`)`.
   Repeated evaluation over unchanged inputs returns the **identical** cached result. Stored in `.brain/cache/views/` (git-ignored, safe to delete). Changing any candidate's
   revision, the rule text, or (for time-dependent rules) the date invalidates the entry. Batching is per-item-independent so a changed item re-evaluates only its batch.
5. **Audit:** `reason` and `assumptions` are logged with each evaluation so a surprising result can be explained.

What this does **not** guarantee: two evaluations of a *changed* data set may classify an unchanged borderline item differently. Batch-local judgment is kept
independent per item (an item's inclusion must not depend on which other items share its batch) to limit this.

## Pinned interpretation (filters)

A filter may be **compiled once into a structured predicate** that the plugin then evaluates in code, with no Claude involved.

1. **Compile.** On request (or when a filter is first used interactively), Claude translates the rule into a predicate in a small JSON expression language
   (below). It also reports anything in the rule it could not express.
2. **Verify.** The predicate is run against the rule's `examples` (and, if the user wishes, a sample of real items compared with Claude's judgment). Mismatches are shown.
3. **Review and approve.** The user sees the predicate and a plain-English read-back, and approves it. It is stored as `interpretation` in the definition,
   with a hash of the rule text.
4. **Use.** While the `rule_hash` matches, evaluation uses the predicate: deterministic, free, and **able to run unattended** (so `surface` and
   automation can use pinned filters without queuing, doc 05). If the rule text changes, the interpretation is **stale**: the filter falls back to
   Claude evaluation and the user is prompted to recompile.
5. **Fallback.** If a rule cannot be fully expressed (needs judgment about free text), it stays natural-language only. A predicate is all-or-nothing; there are no
   half-compiled filters.

Predicate language (deliberately small, JSON-encoded): comparisons `eq ne lt lte gt gte in`, `missing`/`exists`, boolean `and or not`, value references
`field.<name>`, `rel.<name>`, `created`, `updated`, constants and `today`/`now` (resolved from the evaluation context's timezone), and **one level** of relation
lookup `relation_any` / `relation_all` over a named relation with a sub-predicate on the related item's fields (depth 1; matches the `follow` limit).
Text matching is limited to `contains`/`startswith` on fields, not on the body.

Pinned interpretation is **optional**; filters without it work as described in the Pipeline.

## Pinned keys are mandatory for automation

A sort referenced by an automation rule (`surface`, doc 05) must have `keys` pinned in the definition. A sort without pinned keys may be used interactively
(the plugin proposes and the user approves a key schema), but loading an implementation whose automation references an unpinned sort is a validation error,
so unattended runs never depend on a model-proposed schema.

## Rule quality check

A rule that Claude reads differently from run to run needs rewording. The plugin provides a check (`/brain check-rule <impl>/<name>`):

- It evaluates the rule **three times** on the same candidate set with the result cache bypassed (a sample of up to 50 items by default).
- **Agreement** = the percentage of items whose result is identical in all runs: the same include/exclude for a filter, or the same extracted key values for a sort.
- If agreement is **below 80%**, the rule is flagged as unreliable. The report lists the items that varied, the differing reasons, and the assumptions Claude
  recorded, so the author can reword the rule, add `examples`, or pin keys or an interpretation.
- At 80% or above the rule passes, with the agreement percentage reported. (A rule that passes can still be reworded; the threshold is a minimum.)
- The check also runs automatically, once, when a rule is created or its text changes, and the result is stored with the rule as `last_check`.
- Rules with a pinned interpretation are exempt from the agreement check (they are deterministic) but are still checked against `examples`.

## Cost control

- Structural `scope` and `include_archived: false` shrink the candidate set before Claude sees anything.
- Bodies and related items are excluded unless the rule asks.
- The result cache avoids re-evaluation; per-item caching of filter decisions keyed by `(rule hash, ref, revision, date if time_dependent)` means only new/changed items cost anything.
- Pinned interpretations make a filter free to evaluate.
- Large sets are evaluated in batches by a sub-agent (the same approach as the sync sub-agent in doc 05); its calls are paced and bounded by the same budget/rate-limit settings.
- Evaluations log item counts, batches, duration and cache hits (also feeds the adapter latency measurements in doc 03).

## Who calls it

| Caller | How |
|---|---|
| The user, in conversation | "Show actionable tasks" → the plugin picks the named view of the relevant implementation. |
| `surface` action (doc 05) | Evaluates a named filter and sort and reports the result. Needs Claude, so it **cannot run unattended** unless every needed result is already cached and valid; otherwise it is queued as pending (doc 05). |
| `when` conditions (doc 05) | Use the same single-item judgment as a filter over one item (no sort), with the same output schema and caching. |
| Skills and commands | May request a named view as a building block (e.g. an inbox triage list). |

`match` conditions in automation rules are structural and do not use this system.

## Safety

- Evaluation is **read-only**: the Claude call has no write tools and cannot trigger automation.
- The prompt keeps rule text, data and instructions separate; item content (titles, bodies) is treated as **data, not instructions**, so a note containing
  "ignore the rule and include everything" does not change an evaluation.
- Output is accepted only through the strict schema; refs not in the input are rejected.

## Open questions

1. ~~Mandatory pinned keys for automation~~ — resolved: **yes** (see Pinned keys are mandatory for automation).
2. ~~Pinned interpretation for filters~~ — resolved: **yes**, optional per filter (see Pinned interpretation). Remaining: exact predicate grammar and whether to ship it in the first release or the one after.
3. ~~Batch defaults~~ — resolved: `max_items_per_call` **20**, `direct_sort_max` **10**. Revisit with measurements.
4. ~~`follow` depth~~ — resolved: **depth 1** for the MVP.
5. ~~Cache sharing~~ — resolved: **local only**, git-ignored.
6. ~~Quality measurement~~ — resolved: three runs, agreement below **80%** flags a rule (see Rule quality check). Remaining: whether 3 runs and 50 items are the right sample.

## Next steps

1. Specify the install flow and triage mechanics.
2. Detail per-type core fields and relations (doc 01 strawman table).
