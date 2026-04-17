# r001_sonnet — Pragmatic Implementer

**Role**: Builder — the person who ships it and debugs it at 2am.

---

## 1. Recommended Order

**A → B(partial) → skip C → skip D (until triggered)**

Elaborated: A now, then only the non-redundant slice of B, C and D are premature.

---

## 2. ROI Per Item

### A — ARCHITECTURE.md (~half day)

**Effort**: Low. The raw material already exists: 5 pinned memories + the Compost contract + `non-exposed-schema-fields.md`. This is distillation, not invention.

**Value**: High, time-sensitive. Compost Phase 5 adapter is being built *in parallel right now*. Every day without a canonical trust-boundary doc is a day where the adapter author fills the gap with assumptions. Wrong assumptions compound. The "half day" estimate is realistic — it's copy-edit, not design work.

**Verdict**: Do it first. This is the one item where *not doing it* has an active cost accumulating today.

**Rationalization check**: You asked if this is doc-procrastination bias. It's not. The tell for procrastination bias is "this will be useful someday." Here the consumer (Compost Phase 5) is named and active. Do it.

### B — engram lint extension (~1 day)

**Effort**: Medium. But the code already does the heavy lifting. Look at `db.py` lines 35-37:

```
CHECK(origin != 'compost' OR kind = 'insight'),
CHECK(origin != 'compost' OR source_trace IS NOT NULL),
CHECK(origin != 'compost' OR expires_at IS NOT NULL)
```

Schema already blocks `origin=compost` with missing `source_trace` — at the write path, not at lint time. So the first lint check in the candidate list ("origin=compost 无 source_trace") is **pure defense-in-depth against a class of bugs that cannot reach the DB**. That check adds zero real safety margin and wastes test budget.

**The only B checks with real ROI:**
- `expires_at` already past + still `active` — schema cannot enforce this (it's temporal). This is a genuine gap.
- `compost_insight_sources` orphan detection — also genuine, schema cannot prevent a row from becoming an orphan after its parent is deleted/expired.

**Trimmed B effort**: ~3-4 hours, not a full day.

**Verdict**: Do trimmed B after A. The `insight kind non-compost origin` check is redundant (blocked by schema CHECK), skip it.

### C — recall/proactive layering

**Effort**: Medium-high. Touching recall ranking logic is risky — it's load-bearing and the behavior is subtle.

**Trigger condition**: >10 compost entries in production. Current count: **0**.

**Verdict**: Don't touch. You have a documented trigger condition. Respect it. Building this now is YAGNI. The schema already excludes compost from recall by default (`include_compost=False` in `store.py` line 681-682). The problem C solves doesn't exist yet.

### D — GC daemon

**Effort**: Medium + operational risk (scheduling, failure modes, the "永不做清单" constraint tension).

**Trigger condition**: First expired compost entry. Current count: **0**.

**Verdict**: Don't touch. Same reasoning as C. The constraint "NO silent auto-delete" makes this a careful design problem — you don't want to build a daemon that could accidentally violate it under edge cases. Build it when you have a real expired entry to test against, not speculatively.

---

## 3. Fifth Option the User Missed

**B.5 — Expired compost runtime filter hardening**

Right now `store.recall()` filters `expires_at` past entries at query time (line 664 in `store.py`). But `stream_for_compost` and the export path — do they also filter? If a Compost adapter calls `stream_for_compost` and receives a row where `julianday(expires_at) < julianday('now')`, it gets stale data.

This is a 30-minute fix: verify the expiry guard is consistently applied across all read paths. Not a new feature — a correctness check. Cheaper than B and higher actual risk surface than the schema-redundant B checks.

---

## 4. Solo Dev vs Team Perspective

**Team perspective** would say: do B in full (even the redundant checks), because a future maintainer might not know the schema already enforces it, and the lint output serves as documentation. Tests-as-spec argument.

**Solo dev perspective**: you are the future maintainer, you wrote the schema CHECKs, and your test budget is real. Adding tests for behavior that is physically impossible (writing compost without source_trace) means those tests test SQLite's constraint enforcement, not your code. That's SQLite's job.

The "永不做清单" rule 3 ("NO opaque ranking") actually argues *against* full B: if you add lint checks that never fire because they're schema-blocked, you create confusion about what lint actually catches vs what the DB already enforces. Keep the signal clean.

---

## Summary

| Item | Do? | When | Effort | Actual Value |
|------|-----|------|--------|--------------|
| A | Yes | Now | ~4h | High (active dependency) |
| B (trimmed) | Yes | After A | ~3h | Medium (2 real gaps) |
| B (redundant checks) | No | Never | - | Zero (schema does it) |
| C | No | At trigger | - | Zero until >10 compost entries |
| D | No | At trigger | - | Zero until first expired entry |
| B.5 (expiry path audit) | Yes | With B | ~30min | High (correctness gap) |

**Ship A today. Trim B to the two checks schema can't enforce. Verify expiry filter coverage across all read paths while you're in the code. Leave C and D for when the data justifies them.**
