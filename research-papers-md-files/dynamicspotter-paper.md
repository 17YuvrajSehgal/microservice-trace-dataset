# Paper Context: DynamicSpotter (ICPE '15 Demo)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> This is a short (2-page) invited demonstration paper. It describes a tool and its
> architecture. It contains **no experiments, no datasets, and no numeric results**.
> Evaluation results live in the cited papers [8] (ICSE '13) and [9] (QoSA '14), which are
> NOT summarized here. Do not attribute numbers or specific anti-pattern names to this paper
> beyond what is written below.

---

## 1. Bibliographic info

- **Title:** DynamicSpotter: Automatic, Experiment-based Diagnostics of Performance Problems
- **Type:** Invited Demonstration Paper (tool paper), 2 pages (pp. 105–106)
- **Author:** Alexander Wert, Karlsruhe Institute of Technology (KIT), Karlsruhe, Germany (alexander.wert@kit.edu)
- **Venue:** 6th ACM/SPEC International Conference on Performance Engineering (ICPE '15), Jan 31 – Feb 4, 2015, Austin, Texas, USA
- **DOI:** 10.1145/2668930.2693844
- **ISBN:** 978-1-4503-3248-4/15/01
- **Tool homepage:** http://sopeco.github.io/DynamicSpotter/ (open source, GitHub)
- **Status noted in paper:** in 2014 reviewed and accepted by the **SPEC Research Group**; part of SPEC RG's repository of recommended performance evaluation tools.

```bibtex
@inproceedings{wert2015dynamicspotter,
  title     = {DynamicSpotter: Automatic, Experiment-based Diagnostics of Performance Problems},
  author    = {Wert, Alexander},
  booktitle = {Proceedings of the 6th ACM/SPEC International Conference on Performance Engineering (ICPE '15)},
  pages     = {105--106},
  year      = {2015},
  address   = {Austin, Texas, USA},
  publisher = {ACM},
  doi       = {10.1145/2668930.2693844}
}
```

---

## 2. One-paragraph summary

DynamicSpotter (DS) is an open-source framework that **automatically detects performance
problems and their root causes in enterprise software during the testing phase**. It combines
**software performance anti-patterns** (Smith & Williams) with **systematic experimentation**.
Anti-patterns are organized into a **hierarchical taxonomy** from high-level symptoms down to
specific root causes. DS walks this taxonomy as a **decision tree**. At each node it runs a
**detection heuristic**, which defines (1) which experiments to run, (2) which data to collect,
and (3) which analysis rules decide whether the problem exists. DS then produces a **report**
saying, for each taxonomy node, whether the problem is present and **where its root cause is**
in the system under test (SUT). DS does not measure by itself; it plugs in existing tools via
three **extension points**: load generator adapters (e.g., JMeter, Faban), instrumentation
adapters (e.g., DiSL, Kieker, AIM), and measurement adapters. It is designed to run often,
for example inside **continuous integration**.

---

## 3. Problem and motivation

- Performance of enterprise software directly affects customer satisfaction.
- Problems and root causes should be found in the **testing phase**, before end users see them in operation.
- In practice, performance diagnosis is **highly manual** and needs significant performance-engineering expertise, so frequent and thorough analysis is impractical.
- DS goal: **fully automate** running performance test series, collecting measurements, and analyzing data to scan a SUT for **known types** of performance problems and their root causes.

---

## 4. Diagnostics approach (core idea)

1. **Knowledge base = taxonomy of performance problems.**
   - Built from software performance anti-patterns [6].
   - Many anti-patterns share characteristics, so they are arranged hierarchically.
   - The taxonomy spans from **high-level symptoms** to **specific root causes** [8, 9].
2. **Taxonomy used as a decision tree.**
   - DS traverses it systematically, searching top-down for problems.
   - (Implied by decision-tree use: deeper, more specific checks follow once a higher-level symptom is confirmed. The paper does not detail the traversal/pruning rules.)
3. **Detection heuristic per node.** Each heuristic specifies:
   - a set of **experiments** to execute (e.g., load tests under chosen conditions),
   - the **data** to gather (what to instrument and measure),
   - a set of **analysis rules** that decide if the problem exists in the SUT.
4. **Output: diagnostics report.**
   - For each taxonomy node: does the problem exist?
   - If yes: **pointer to the root-cause location** in the SUT.

Key properties:
- **Experiment-based (active):** DS designs and runs experiments, not just passive monitoring.
- **Knowledge-driven:** only finds **known** problem types covered by the taxonomy and heuristics.
- **Reusable knowledge:** taxonomy and heuristics are **generic artifacts** made by performance experts and reused across applications.

---

## 5. Architecture (Figure 1)

### 5.1 Roles and inputs

- **Performance Expert:** provides the **Taxonomy on Performance Problems** and **Detection Heuristics** (both are extension points).
- **DynamicSpotter User:** writes a **configuration** that describes the Measurement Environment.

### 5.2 Main components

- **DynamicSpotter Core**
  - **Process Controller:** implements the high-level process of iterating the taxonomy; coordinates the SUT instrumentation, measurement process, data gathering and pre-processing, and analysis.
  - **Experiment Execution:** automates experiment execution.
  - **Data Analysis:** analyzes measurement data per problem using the rules in the detection heuristics.
- **DynamicSpotter Service:** service component connected to the Core (the paper does not describe it further).
- **Front ends:**
  - **DS Runner:** headless process that takes a configuration file (suited to automation / CI).
  - **DS Eclipse-Plugin:** interactive way to create a configuration.

### 5.3 Extension points (<<EP>>) and adapters

| Extension point | Role | Example tools named |
|---|---|---|
| Load Driver / Load Generator Adapter | Use existing load generators for workload generation | Apache JMeter, Faban |
| Instrumentation Adapter | Use instrumentation tools to instrument the SUT | DiSL, Kieker, AIM (Adaptable Instrumentation and Monitoring, the authors' own tool) |
| Measurement Adapter | Control data collection; transform and transfer data from monitoring tools into a **common data representation format** | (tool-specific) |

- DS uses a **generic Instrumentation Description Model (IDM)** to decouple *what* to instrument from the tool that does it.
- Instrumentation and measurement adapters are often implemented in the same external tool but are **conceptually different tasks**.
- Multiple adapters of each kind can be used. The **selected set of adapters defines the Measurement Environment** (load generators + measurement tools + instrumentation tools around the SUT).

### 5.4 Workflow in practice

1. Expert supplies taxonomy + heuristics (reusable).
2. User configures the Measurement Environment (Runner file or Eclipse plugin).
3. DS Core walks the taxonomy; per node: instrument SUT → generate load → collect data → apply analysis rules.
4. DS outputs a report of detected problems and root-cause locations.

---

## 6. Conclusion and future work (as stated)

- DS applied in multiple case studies [8, 9] with "promising results" for automating diagnostics (no numbers in this paper).
- Diagnostic power **depends on the available detection heuristics**.
- Currently available heuristics: **software bottlenecks** and **communication performance anti-patterns**.
- Future work: extend the set of detection heuristics; add adapters for common measurement tools (e.g., **Kieker**).

---

## 7. References cited by the paper

1. AIM homepage: http://sopeco.github.io/AIM/
2. DynamicSpotter homepage: http://sopeco.github.io/DynamicSpotter/
3. Faban: http://faban.org/
4. Apache JMeter: http://jmeter.apache.org
5. Marek et al., DiSL: a domain-specific language for bytecode instrumentation, AOSD '11/'12, ACM.
6. Smith & Williams, Software performance antipatterns; common performance problems and their solutions, CMG 2002.
7. van Hoorn, Waller, Hasselbring, Kieker: A framework for application performance monitoring and dynamic software analysis, ICPE '12.
8. Wert, Happe, Happe, Supporting swift reaction: automatically uncovering performance problems by systematic experiments, ICSE '13. (Main method + evaluation paper.)
9. Wert, Oehler, Heger, Farahbod, Automatic detection of performance anti-patterns in inter-component communications, QoSA '14.

If precise results, the full taxonomy, or specific heuristics are needed, cite [8] and [9], not this demo paper.

---

## 8. Ambiguities and limits of this paper

1. No evaluation, dataset, accuracy, overhead, or runtime numbers.
2. Taxonomy nodes and heuristic rules are not listed; only the two covered families are named (software bottlenecks, communication anti-patterns).
3. Traversal details (pruning, order, stopping) of the decision tree are not given.
4. "Root cause location" granularity (method, component, call) is not specified here.
5. The DynamicSpotter Service component's role is not explained.
6. The reference to Kieker appears both as a supported instrumentation example and as future adapter work, which suggests support was partial at the time.
7. Targets Java-era enterprise systems (DiSL is JVM bytecode instrumentation); applicability to microservices or cloud-native systems is not discussed.

---

## 9. How to cite it (safe claims)

- DS automates experiment-based diagnosis of performance problems and root causes in the testing phase.
- It uses a hierarchical taxonomy of performance anti-patterns as a decision tree, with a detection heuristic (experiments + data + analysis rules) per node.
- It is tool-agnostic via load-generation, instrumentation, and measurement adapters (JMeter, Faban, DiSL, Kieker, AIM), with a generic instrumentation description model.
- It is open source and was accepted into SPEC RG's recommended tools repository (2014).
- It detects only known problem types; capability depends on expert-provided heuristics.

---

## 10. Reusable ideas

- **Taxonomy-as-decision-tree** for diagnosis: go from symptom to root cause step by step.
- **Heuristic = (experiments, data, rules)** as a clean, pluggable unit of diagnostic knowledge.
- **Active experimentation:** run targeted experiments to confirm a hypothesis, instead of only mining passive telemetry.
- **Adapter / extension-point architecture** to stay independent of load, tracing, and monitoring tools; a generic instrumentation description model.
- **Headless runner for CI** plus an interactive configuration UI.
- **Separation of roles:** experts encode knowledge once; users reuse it across systems.

## 11. Gaps a newer paper can target

- Manual, expert-built taxonomy and rules → could be learned or generated (e.g., by ML or LLM agents).
- Only known problem types → no discovery of new patterns (contrast: Performance Archetypes discovers patterns by clustering).
- Testing-phase focus → not designed for production incidents or online RCA.
- Single-application enterprise (Java) focus → no microservice propagation or multi-source trace/metric fusion.
- No reported accuracy, cost, or time in this paper.

---

## 12. Links to the other two papers in context

| Aspect | DynamicSpotter (ICPE '15) | Performance Archetypes (ASE '26) | MSoFSAnomaly (JSS '25) |
|---|---|---|---|
| Goal | Find known perf problems + root cause in testing | Discover recurring perf patterns + detect regressions | Detect failures and output pure anomalous data for RCA |
| Knowledge source | Expert taxonomy of anti-patterns | Learned by k-means clustering (13 archetypes) | Learned by Transformer reconstruction |
| Data | Chosen per heuristic (instrumentation, load tests) | Static code + function traces + kernel events | K8s metrics + distributed traces |
| Mode | Active experiments | Passive traces over many randomized inputs | Passive monitoring |
| Structure focus | Symptom → root-cause tree | Critical paths in call tree | Leaf services in call tree |
| Output | Report per taxonomy node + root-cause location | Archetype labels, anomaly score, bottleneck | Alarm + top-3 (service, feature) |
| Evidence | None in this paper (see [8], [9]) | F1 0.867 | P 97.16 / R 97.85 (OB) |

Common thread: all three narrow the search to the part of the system that matters (taxonomy
branch, critical path, fault-sensitive services). DynamicSpotter is the older, rule-based,
expert-knowledge baseline; the two newer papers replace expert rules with data-driven learning.
