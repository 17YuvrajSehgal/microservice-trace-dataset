# Paper Context: DrAsync — Identifying and Visualizing Anti-Patterns in Asynchronous JavaScript (ICSE 2022)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The source for the **`code_serial_awaits`** fault family, which has no blueprint yet. Its
> **`loopOverArrayWithAwait`** anti-pattern is our fault, named. **But read §8 before using it:**
> the paper's own performance results are weak, and it says plainly why.

---

## 1. Bibliographic info

- **Title:** DrAsync: Identifying and Visualizing Anti-Patterns in Asynchronous JavaScript
- **Authors:** Alexi Turcotte, Michael D. Shah, Frank Tip (Northeastern University);
  Mark W. Aldrich (Tufts University)
- **Venue:** ICSE 2022, 21-29 May, Pittsburgh. 12 pages.
- **DOI:** 10.1145/3510003.3510097

```bibtex
@inproceedings{turcotte2022drasync,
  title     = {DrAsync: Identifying and Visualizing Anti-Patterns in Asynchronous JavaScript},
  author    = {Turcotte, Alexi and Shah, Michael D. and Aldrich, Mark W. and Tip, Frank},
  booktitle = {ICSE 2022}, year = {2022},
  doi       = {10.1145/3510003.3510097}
}
```

---

## 2. One-paragraph summary

`async`/`await` arrived in JavaScript in 2017 and the community adopted it fast, but *"many
JavaScript programmers are still unfamiliar with asynchronous programming, and particularly with
async/await and how it interacts with promises."* The authors define **8 anti-patterns** in
promise-based code, detect them with **lightweight static analysis** (CodeQL), and pair that with
a **dynamic analysis** that tracks promise lifetimes so you can see which anti-patterns actually
run. They find **2.6K static instances in 20 popular JavaScript repositories**, executed **24K
times** by the projects' own test suites. They then try to refactor a sample: **65 of 80 succeed**.
Performance gains are **small and hard to find** — and the discussion section explains why.

---

## 3. The eight anti-patterns

| Key | Name | What it is |
|---|---|---|
| **P1** | `asyncFunctionNoAwait` | an `async` function with no `await` in it — creates a promise for nothing |
| **P2** | **`loopOverArrayWithAwait`** | **a `for` loop over an array whose body contains an `await`** |
| **P3** | `asyncFunctionAwaitedReturn` | `return await x` — the `await` is redundant |
| **P4** | `explicitPromiseConstructor` | `new Promise` that just mirrors an existing promise |
| **P5** | `customPromisification` | hand-rolled promisification of a callback API instead of `util.promisify` |
| **P6** | `promiseResolveThen` | `Promise.resolve(e).then(f)` — a promise built only to attach a reaction |
| **P7** | `reactionReturnsPromise` | a `.then` reaction returning `Promise.resolve`/`reject` |
| **P8** | `executorOneArgUsed` | an executor that only ever resolves, or only ever rejects |

Two of the eight (`explicitPromiseConstructor`, `customPromisification`) came from **searching
Stack Overflow**, not from the authors' imagination.

### P2 in their words — this is `code_serial_awaits`

> covers `for`-loops of the form `for(e0; e1; e2){s}` where the condition tests
> `Array.prototype.length` and the body contains at least one `await`-expression. **This situation
> is well-known in the JavaScript community as being needlessly inefficient in situations where
> the iterations of the loop are independent of one another**, and the ESLint checker has a rule
> for detecting it. In many cases, such loops can be refactored to use **`Promise.all`** and
> `Array.prototype.forEach` to enable additional parallelism.

**Note the condition: "where the iterations are independent."** The pattern is only a bug when
the awaits did not need to be ordered. Static analysis cannot tell.

---

## 4. Prevalence — 20 repositories

Their Table 3. `S` = static occurrences, `(E)` = those actually executed by the test suite,
`D` = runtime promises associated with the anti-pattern.

| Anti-pattern | Static | Executed | Runtime promises |
|---|---|---|---|
| P1 `asyncFunctionNoAwait` | **1401** | 76 | 7893 |
| **P2 `loopOverArrayWithAwait`** | **293** | **30** | **5401** |
| P3 `asyncFunctionAwaitedReturn` | 458 | 18 | 4053 |
| P4 `explicitPromiseConstructor` | 39 | 13 | 299 |
| P5 `customPromisification` | 106 | 17 | 1231 |
| P6 `promiseResolveThen` | 63 | 13 | 2068 |
| P7 `reactionReturnsPromise` | 72 | 17 | 425 |
| P8 `executorOneArgUsed` | 159 | 21 | 2604 |

**The E column is the interesting one.** Only **30 of 293** `loopOverArrayWithAwait` instances
are exercised at all by the test suites. Static counts wildly overstate what runs — which is
exactly why they built the dynamic half.

Projects include `fastify`, `strapi`, `stencil`, `vuepress`, `netlify-cms`, `vscode-js-debug`,
`eleventy`, `treeherder`, `dash.js`, `appcenter-cli`, `CodeceptJS`, `flowcrypt-browser`.

---

## 5. Can they be refactored? (RQ2)

They sampled **10 instances of each anti-pattern** and refactored by hand.

- **65 of 80 succeeded.**
- Of the 15 failures, they note *"not all are necessarily false positives"* — a developer with
  more context might manage them.
- Conclusion: **the majority of problematic code DrAsync reports can be eliminated by
  refactoring.**

---

## 6. Does it make anything faster? (RQ3) — the honest section

They pick three instances chosen to be favourable — frequently executed, many promises, or
enabling concurrency.

| Case | Anti-pattern | Result |
|---|---|---|
| **`appcenter-cli/cpDir`** — copy a 7.8 GB directory of 37 files, 50 runs | **P2** | **16.4% faster (4.8 s vs 5.8 s)**, and **variance 37.9% smaller** (0.33 s vs 0.54 s) — more predictable |
| **`vuepress/apply`** — refactored to `Promise.all`, test suite 50 runs | **P2** | **36.1% faster** for that fragment; **run-time variability down 16%** |
| **`strapi/evaluate`** — 5 fewer runtime promises per execution | P6 | **4% faster**, standard deviation down 7.4% |

**Then the whole-project experiments, which found nothing:**

- **eleventy** — refactored *every executed anti-pattern instance*: **1.1K fewer promises**
  (39,978 → 38,748) and **no meaningful change in test-suite run time**.
- **vuepress** — same experiment: **1.2K fewer promises** (32,264 → 31,021) and again **no
  meaningful change**.

Their explanation, quoted because it is the most important sentence in the paper for us:

> *"It is difficult to measure the effect of the removal of runtime promises on the overall
> performance of applications, due mostly to their asynchronous nature. **Even if thousands of
> redundant promises are eliminated, it is possible that the application was waiting on another
> operation which takes longer than the sum total of the lifetimes of the eliminated
> promises.**"*

Their final claim is deliberately hedged: eliminating anti-patterns *"may speed up the execution
of the **affected code fragments**"* — not the application.

---

## 7. What kind of paper this is

- A **static analysis (CodeQL) + dynamic analysis + interactive visualisation tool**.
- JavaScript / Node.js only.
- The contribution is **detection and developer insight**, not a performance result.
- Evidence is **source code, promise lifetimes, and test-suite timings** — no OS-level data.

---

## 8. What this means for our work

**It gives `code_serial_awaits` its name and its fix.** `loopOverArrayWithAwait` → refactor to
`Promise.all`. It is common enough to have an **ESLint rule**, appears **293 times in 20
repositories**, and the community already considers it *"needlessly inefficient"*. That is
adequate grounding for the fault family.

**But it is weak evidence that the fault matters, and we should say so.** The two cases that
looked good — 16.4% and 36.1% — were **hand-picked for being favourable and measured on the
affected fragment only**. When they refactored *everything* in two projects, they measured
**nothing at all**. Our reference notes for this family should carry that, not just the two
positive numbers.

**Their failure to measure it is an argument for our modality, and it is a sharp one.** Their
reason is precise: *the eliminated promise lifetimes are hidden inside a longer wait.* That is a
**wall-clock** problem. It does not apply to a count. `code_serial_awaits` means **N sequential
round trips instead of one concurrent batch**, and in a kernel trace that is:

| | Serial awaits | `Promise.all` |
|---|---|---|
| Round trips | N | N |
| **Overlap** | **none — each `sendto` follows the previous `recvfrom`** | **N sends before the first receive** |
| Total time | **N × latency** | ≈ 1 × latency |

**The discriminator is overlap, not count.** Both versions issue the same number of syscalls; only
the serial one never has two requests in flight. That is directly measurable from send/receive
timestamps on the socket, and it is invisible to every method in this paper. **This is the
sharpest "kernel traces see what source analysis cannot" case in the whole `code_*` family** —
and it is a hypothesis to test on our runs, not a finding.

**It also separates `code_serial_awaits` from `code_n_plus_one`**, which otherwise look similar:

| | `code_n_plus_one` | `code_serial_awaits` |
|---|---|---|
| Round trips | **many more than necessary** | **the right number** |
| Concurrency | irrelevant | **zero, where it should be N** |
| Fix | batch the query | `Promise.all` |

**One caution the paper hands us for free.** P2 is only a defect *"where the iterations of the
loop are independent"*. If our injected fault makes the awaits serial in a place where they had
to be ordered anyway, we have injected nothing. Worth checking the recipe.

**And one about scale.** Their biggest measured effect came from a **7.8 GB directory copy** —
long, I/O-bound iterations. Sock Shop's front-end awaits are short HTTP calls to services on the
same host. **The effect size scales with per-iteration latency**, so our injection needs enough
items, or enough latency per item, to show up at all. Same calibration risk as
`code_n_plus_one`.

---

## 9. Safe claims

- `async`/`await` was added to JavaScript in 2017 and widely adopted, but many programmers are
  unfamiliar with how it interacts with promises.
- DrAsync defines **8 anti-patterns**, detects them by **static analysis**, and uses **dynamic
  analysis** to record promise lifetimes and which instances actually execute.
- **2.6K static instances found across 20 popular JavaScript repositories**, executed **24K
  times** by the projects' test suites.
- **`loopOverArrayWithAwait`**: a `for` loop over an array with an `await` in the body. **293
  static instances, only 30 executed, 5,401 runtime promises.** It is *"well-known in the
  JavaScript community as being needlessly inefficient"* **when the iterations are independent**,
  has an **ESLint rule**, and is refactored with **`Promise.all`**.
- **65 of 80 sampled instances were successfully refactored** by hand; the 15 failures are not
  necessarily false positives.
- Measured speedups, on hand-picked favourable fragments: **16.4% with 37.9% lower variance**
  (`appcenter-cli/cpDir`, 7.8 GB, 50 runs); **36.1% with 16% lower variability**
  (`vuepress/apply`); **4%** (`strapi/evaluate`, P6).
- **Refactoring every executed instance in eleventy and vuepress removed ~1.1K and ~1.2K runtime
  promises respectively and produced no meaningful change in test-suite run time.**
- The authors' explanation: eliminated promise lifetimes are often **hidden inside a longer wait
  on something else**.
- Two of the eight anti-patterns were found by searching **Stack Overflow**.

## 10. Do NOT claim

- That eliminating these anti-patterns speeds up applications. The paper's own whole-project
  experiments found **no meaningful change**, twice; the positive numbers are for **selected code
  fragments**.
- That 2.6K instances are 2.6K bugs. Only **~190 of 2,591** were executed at all by the test
  suites, and P2 is only a defect when loop iterations are independent.
- That it measures anything at the OS level. It observes **promise lifetimes** inside the runtime.
- That the 16.4% and 36.1% are typical. Both were chosen for being favourable, and the larger one
  involved copying a 7.8 GB directory.

## 11. Reusable ideas

- **Separate static occurrences from executed ones.** Their `S (E)` columns — 293 found, 30 run —
  is the single most honest table in the `code_*` reference set, and it is the reason their tool
  is usable.
- **Report the experiment that found nothing.** Refactoring all of eleventy and measuring no
  change is what makes the 36.1% believable.
- **Explain why your measurement failed.** "The savings were hidden inside a longer wait" is a
  mechanism, not an excuse, and it points straight at what to measure instead.
- **Mine Stack Overflow for the taxonomy.** Two of eight anti-patterns came from what people
  actually ask about.
- **Variance is a result too.** Their refactorings cut run-time variability by 16-38%, which
  matters for tail latency even when the mean barely moves.
