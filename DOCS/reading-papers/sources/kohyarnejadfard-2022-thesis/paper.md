# Paper Context: System Performance Anomaly Detection using Tracing Data Analysis (PhD thesis, Polytechnique Montreal 2022)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
>
> **140-page article-based thesis**, three articles. **Chapter 6 is the Journal of Cloud
> Computing 2022 paper we also hold separately** as `kohyarnejadfard-2022-anomaly`. This
> summary covers the thesis arc plus Chapter 6 in detail.
>
> Read §9 first. This is the closest published work to ours in *data source* - LTTng kernel
> traces of microservices - and the furthest in *goal*. It detects anomalies; it does not
> localise root causes. That difference is our gap.

---

## 1. Bibliographic info

- **Thesis:** Iman Kohyarnejadfard, *System Performance Anomaly Detection using Tracing Data
  Analysis*, PhD thesis, Polytechnique Montreal, 2022. 140 pp.
  https://publications.polymtl.ca/10281/1/2022_ImanKohyarnejadfard.pdf
- **Chapter 6 = the article:** Kohyarnejadfard, I., Aloise, D., Azhari, S. V., Dagenais, M. R.
  "Anomaly detection in microservice environments using distributed tracing data analysis and
  NLP." **Journal of Cloud Computing 11:25, 2022.** DOI 10.1186/s13677-022-00296-4
- Chapters 4 and 5 are two earlier articles on the same theme.

```bibtex
@article{kohyarnejadfard2022anomaly,
  title   = {Anomaly detection in microservice environments using distributed tracing data analysis and NLP},
  author  = {Kohyarnejadfard, Iman and Aloise, Daniel and Azhari, Seyed Vahid and Dagenais, Michel R.},
  journal = {Journal of Cloud Computing}, volume = {11}, pages = {25}, year = {2022},
  doi     = {10.1186/s13677-022-00296-4}
}
```

---

## 2. One-paragraph summary

The thesis asks how to find performance anomalies in complex systems from **LTTng tracing
data**, without a human reading thousands of low-level events. Three articles, increasingly
ambitious. The first classifies **windows of system calls** with an SVM, using the **duration**
of each syscall as a weighted frequency. The second handles the practical problem that labelled
data usually does not exist, offering supervised and unsupervised variants depending on how
much you have. The third - the one we cite - treats a **span as a sentence**: events are words
that follow grammar-like patterns, so an **LSTM** trained only on normal traces can predict the
next event, and a surprise means an anomaly. It reports **F-score 0.9759**, needs **no labelled
data**, and also detects **release-over-release regressions**.

---

## 3. The thesis problem statement

- Distributed systems, microservices, IoT and cloud are increasingly complex; one task spans
  many cores and nodes, and the same operation may be served differently each time.
- Causes of anomalies they list: network distribution, mixed technologies, **short service
  lifetimes**, software bugs, hardware failures, resource contention.
- Tracing an OS or application means **thousands of low-level events per second**, which adds
  overhead that can itself disturb the target.
- Hence LTTng, for high throughput at low overhead across kernel, applications and libraries.
- **The real problem is what comes after collection:** "without an automated diagnostic tool,
  system experts have to examine a massive amount of low-level tracing data to determine the
  cause of a performance issue, which is really time-consuming and tedious in practice."

That sentence is the motivation for our work too, almost word for word.

---

## 4. The three contributions

**Article 1 (Ch. 4) — syscall vector anomaly detection.** System-call streams are split into
short sequences with a **sliding window**. The novelty they claim: **the duration of the most
important system calls is part of the feature vector**, so duration acts as a weighted
frequency. An **SVM** classifies windows as anomalous.

**Article 2 (Ch. 5) — coping with label scarcity.** Techniques chosen by how much labelled data
exists: a supervised technique when there is a lot, and alternatives when there is little or
none.

**Article 3 (Ch. 6) — NLP on distributed traces.** The one we cite. Detailed below.

---

## 5. Chapter 6 — the method we cite

### The core analogy

> "Similar to words in natural language processing, events as elements of a sequence follow
> specific patterns and grammar rules."

Their reasoning: only a limited number of events can follow a given action, so only a few of
the possible events can plausibly come next. Train a model on normal traces to predict the next
event; when the real next event is improbable, that is an anomaly.

**They argue explicitly for collective anomalies over point anomalies:** "A single data point
(event or metric), regardless of the data points that occurred around it, does not include
enough information to determine whether an anomaly happened in complex systems such as
microservices."

### What makes it different from neighbours

- **LTTng instead of OpenTracing/Jaeger/Zipkin.** Their argument: an OpenTracing trace is a DAG
  of spans giving only **relationships across microservices**, while LTTng gives **kernel and
  userspace events** - "higher resolution".
- **Events *with their arguments*.** The LSTM predicts the next event's **arguments** (event
  type, tag, process name) as well as its name. They state that prior deep-learning and
  NLP-based work **ignores event arguments**.
- **Unsupervised.** Only normal data is needed, which "can be done automatically without any
  supervision". They note labelling performance data is "highly complicated and sometimes even
  impossible", and needs a very specialised professional.
- **A handcrafted Trace Compass module** builds spans from request/response event tags, and
  uses the hierarchy of those tags to extract **sub-spans**.
- **Release-over-release regression detection** as a second use, on the grounds that
  conventional performance tests do not reveal enough regressions.

### Setup and data

- Target system: a microservice environment **developed by Ciena Co.**
- **Two nodes**, each 2-core Intel (Broadwell, IBRS), **4 GB RAM**, Oracle Linux.
- LTTng on both, with **`lttng-relayd`** on a manager VM collecting remote trace data.
- Training data: **12 traces, 5-10 minutes each**, from **previous stable releases**.
- After removing incomplete spans: **61,709 spans**, **4,028 unique keys**.
- Data collection in Python via the **Trace Compass scripting feature**; LSTM in **PyTorch**;
  trained on 2× Xeon Bronze 3104 with an **NVIDIA TITAN V**.
- Code released: `github.com/kohyar/LTTng_LSTM_Anomaly_Detection`

### Model and evaluation

- **Two hidden LSTM layers**, α blocks per layer, categorical cross-entropy loss.
- Framed as **multi-class classification over 4,028 classes** (one per key), scored with
  per-class precision/recall/F-score then averaged.
- **Window size α tuned over 8-30.** Minimum sequence length in training data is 8; performance
  **decreases above α = 19**; **α = 17** chosen as the best trade-off of F-score against
  training time.
- **Reported result: F-score 0.9759.**

---

## 6. What the numbers actually mean

The 0.9759 F-score is **not** "97.6% of anomalies detected". It is the averaged multi-class
F-score for **predicting the next key out of 4,028 classes** on their training distribution.
Anomaly detection is then derived from prediction surprise. Those are different quantities, and
the paper does not report a separate detection precision/recall against labelled injected
faults.

Anomalies were **injected through simulated scenarios** (their §6.5.3), but the thesis text
around the evaluation does not give a per-fault detection breakdown the way our matrices do.

---

## 7. Where this sits relative to the other DORSAL work

| Work | Data | Output |
|---|---|---|
| Giraldeau 2016 | kernel events, one or more hosts | **why a task waited** (active path) |
| Nemati 2019/2022 | host hypervisor events | same, **through virtualisation layers** |
| Rezazadeh 2020 | kernel + user-space lock events | **who holds a lock, who waits** |
| **Kohyarnejadfard 2022** | **LTTng kernel + userspace, per span** | **whether this span is abnormal** |

The first three explain *what happened*. This one decides *whether something is wrong*. It is
the detection end of the same lab's pipeline.

---

## 8. What this means for our work

**This is the closest published work to ours in data source.** LTTng, microservices, Trace
Compass, low-level kernel events, Dagenais's lab. If a reviewer asks "has this been done", this
is the paper they mean.

**And it is clearly different in goal, which is our contribution.**

| | Kohyarnejadfard 2022 | Ours |
|---|---|---|
| Question | *is this span anomalous?* | *which container caused it, and when?* |
| Output | an anomaly score per span, plus a highlighted region | a named container (`pid_ns`), a time window, and an explanation |
| Method | LSTM over event sequences, learned | a written blueprint, executed by an agent |
| Training | 12 traces of normal behaviour needed | none - the blueprint carries the knowledge |
| Labels | none needed | ground truth used **only** for scoring |
| Generalises by | learning the normal patterns of *that* system | reusing method across systems |

**The honest framing for related work:** existing kernel-trace work on microservices does
**detection** and leaves localisation to a human with a visualisation. We do **localisation**,
and we test whether written method helps an agent do it. Their own framing supports this - they
say the visualisations "direct the debugger to the most relevant problem sites", i.e. a human
still finishes the job.

**Two of their design choices are arguments we can reuse.**

1. **Collective over point anomalies.** "A single data point does not include enough
   information." That is the same reason our discriminators compare a window against a baseline
   rather than threshold a single value.
2. **LTTng over OpenTracing.** Their stated reason - span DAGs give only inter-service
   relationships, kernel events give execution detail - is the same argument we make for the
   kernel modality against RCAEval's trace data.

**One limitation of theirs we should note, carefully.** Their model is trained on **12 traces
from previous stable releases of one system**. That is a per-deployment model: it learns what
normal looks like *here*. Our blueprints are meant to transfer across applications, and our
Sock Shop / Train Ticket split is what tests that. Worth stating as a difference in ambition,
not as a criticism - their approach is well suited to a CI regression gate, which is one of
their stated uses.

**A caution about citing the F-score.** 0.9759 is a multi-class next-key prediction score, not
a fault-detection rate. Do not put it beside our WHERE numbers as if they measure the same
thing.

---

## 9. Safe claims

- LTTng kernel and userspace tracing is an accepted data source for microservice anomaly
  detection in the peer-reviewed literature.
- Events in a trace follow grammar-like patterns, so NLP sequence models apply; the authors
  model spans as sequences of keys and use an LSTM.
- Their approach needs **no labelled data** - only normal traces - because labelling
  performance data is impractical and sometimes impossible.
- Their model predicts the **next event's arguments** (type, tag, process name) as well as its
  name, which they state prior deep-learning approaches ignore.
- **Reported F-score 0.9759**, as an averaged multi-class score over **4,028 classes**, with
  window size **α = 17**; performance degrades above α = 19.
- Training data: 12 traces of 5-10 minutes from previous stable releases, yielding **61,709
  spans**.
- OpenTracing tools (Jaeger, Zipkin) give a DAG of spans describing relationships across
  microservices, but **not kernel events**; the authors treat that as insufficient to
  characterise execution status.
- Point anomalies are insufficient in complex systems - a single event or metric lacks the
  context to decide.
- The framework also detects **release-over-release regressions**.
- Implementation is open source.

## 10. Do NOT claim

- That 0.9759 is a fault-detection rate. It is multi-class next-key prediction, averaged.
- That the file on disk is the journal article. **It is the 140-page thesis**; Chapter 6 is the
  article, which we also hold separately.
- That this localises root causes. It highlights anomalous regions for a human to investigate.
- That the method transfers across systems without retraining. The model is trained on traces
  from the specific system's earlier releases.

## 11. Reusable ideas

- **A span is a sentence.** Treating event sequences as language is a clean way to get
  structure without labels.
- **Predict the arguments, not just the event.** Their stated differentiator, and the reason
  their model catches subtler changes.
- **Tune the window and report the curve.** They show F-score *and* F-score/training-time
  against α, then justify the choice. That is how a hyperparameter should be reported.
- **Say why the easy data source is not enough.** Their OpenTracing-versus-LTTng paragraph is a
  model for how we should argue for the kernel modality.
- **Design for the case where labels do not exist.** Their Article 2 is entirely about this,
  and it is the realistic condition in production.
