# Iterative Prompting

The loop that takes a prompt from "draft" to "locked, safe to run on thousands of
records". Use it for every prompt that makes a language judgement: ICP
qualification, contact tiering, sector classification, observations, bridges,
subject lines, any classifier.

**Where this fits in the pipeline:** phases 0 and 2, list building. That is where
the classifiers live - deciding whether a company fits your ICP, which persona a
title maps to, how to score a list. Get those wrong and you spend the rest of the
run enriching and writing to the wrong companies. It applies again in phase 6 for
copy generation, but the expensive mistakes are made earlier.

---

## The loop

```
Round 1 (anchor)  -> 1 sample    -> you edit it -> capture what you changed
Round 2           -> 10 FRESH    -> you edit    -> revise the prompt
Round 3+          -> 10 FRESH    -> you edit    -> revise the prompt
...
Lock when:        -> 2 consecutive rounds with ZERO edits on 10 fresh samples
On lock:          -> save the prompt, save the approved samples, then run production
```

Two clean rounds, not one. One can be luck.

---

## Before you run it on a batch: the sample-size ladder

The loop above is the design phase. Before a locked prompt touches a large batch,
walk it up:

```
Design    -> 10 fresh, 2 zero-edit rounds -> LOCK
Validate  -> 20 fresh  -> 98%+ against your own labels -> continue
          -> 50 fresh  -> 98%+ -> continue
          -> 300 fresh -> 98%+ -> continue
          -> run it
```

Scale the bar to the blast radius:

| Records affected | Ladder | Bar at each rung |
|---|---|---|
| One-off | skip the ladder | n/a |
| Under 100 | 10 -> all | 98% at 10 |
| 100 - 1,000 | 10 -> 50 -> all | 98% at each |
| 1,000 - 10,000 | 10 -> 20 -> 50 -> 300 -> all | 98% at each |
| Over 10,000, or anything client-facing | add a 1,000 rung | 99% at each |

**Stop at the rung where accuracy first drops.** A prompt that is 95% right at 10
examples can collapse to 80% at 50, because 50 samples stretch the rules into edge
cases the first 10 never contained. Do not roll forward "to see what happens at
full scale". A classifier that was only checked in aggregate corrupted over a thousand
records for us before anyone looked at a single row.

**Counts are not accuracy.** A dry run that reports "P3 dropped by over 90%" tells
you something happened. It does not tell you the something was correct. Score
against your own labels, per record, on a stratified sample.

---

## The rules

**1. Always start with one anchor.** One example, edited by a human, becomes the
gold standard everything else is measured against. Skip it and you have nothing to
measure convergence against.

**2. Fresh samples every round.** Never reuse examples between rounds. Reusing them
teaches the prompt your examples; fresh ones teach it the pattern. Pull the 10 from
different sectors, sizes and signals so the distribution is stretched.

**3. Run the round in parallel.** Fan out all 10 in one go, not one at a time.
Sequential is ten times slower for no benefit.

**4. Extract the pattern, not the edit.** After editing, write down what you
changed at the level of a rule: tone, length, structure, a banned phrase, whether
to assert or hedge. A rule catches every future violation. A fixed example fixes
one example.

**5. Decide the output format before round 1.** JSON with named fields? A single
line with no trailing punctuation? Three bullets? Whatever production consumes, the
rounds produce exactly that. Do not iterate on prose and hope it converts.

**6. Keep the prompt tight.** No "think step by step" padding, no "explain your
reasoning". Context, rules, input, output format. You want what production will
see, not a reasoning trace.

**7. Save the locked prompt somewhere versioned, not in a local text file.** Local
prompt files go stale, drift from what is actually running, and get picked up by
accident. Store the prompt text, the model it is pinned to, and a note on how many
rounds it took and what the edit patterns were. Save the approved samples next to
it so a future re-calibration can re-anchor instead of starting over.

**8. Ask for clarifying questions when the spec is loose.** When you kick off a new
prompt, end your instruction with "ask me 5 clarifying questions before you start".
You do not yet know what to specify, and the questions surface the edge cases,
format ambiguities and validation thresholds you would otherwise hardcode badly.
Skip this for a locked prompt running a routine round.

---

## Anti-patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| The same 10 examples every round | The prompt memorises them and never generalises | Fresh 10 each round |
| Locking after one clean round | Might be luck | Two consecutive |
| No anchor | Nothing to measure against | Round 1 on a single sample |
| Judging by aggregate counts | Tells you something happened, not that it was right | Per-record scoring against your labels |
| Running production before locking | Buys bad data at full price, and it reaches real people | Lock, walk the ladder, then run |
| Prompt in a local .txt | Goes stale, diverges from what runs | Versioned store, pinned model |
| Fixing the example, not the rule | Fixes one case out of a class | Encode the pattern as a rule |

---

## Cost

The design rounds are small - tens of items. Use whatever is cheapest and closest
to hand; the reasoning quality is the product and the volume is trivial.

The validation rungs and the production run are where money gets spent. Default to
a small model there and **state the estimated cost before you start**: how many
records, which model, what it comes to. An estimate that turns out to be double is
not permission to continue - stop, re-estimate, decide again.

Bad output is a prompt problem until proven otherwise. Iterate the prompt before
you reach for a bigger model; a large model in a bulk loop is 10-30x the cost and
almost never the reason quality is bad.
