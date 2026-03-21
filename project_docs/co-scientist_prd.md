**Product Requirements Document**

ML Laboratory Co-Scientist

Local-first, literature-guided autonomous experimentation for machine learning

Status: Working draft  •  Intended use: build planning and collaborative scoping

Prepared on March 20, 2026

| PRD summary • The first release is an ML laboratory, not a generalized science platform. • The MVP is evaluated on Kaggle competition workflows and an existing internal research corpus. • The literature loop is metadata-first: titles and abstracts first, full papers only on shortlist. • The product is local, single-user, bounded by budgets, and human-gated for external actions. |
| :---- |

**1\. Document control**

| Product | ML Laboratory Co-Scientist |
| :---- | :---- |
| **Document type** | Product Requirements Document (PRD) |
| **Version** | 0.1 |
| **Status** | Working draft for planning |
| **Primary owner** | Founding product / research team |
| **Intended deployment** | Local, single-user MVP |
| **Initial domain** | Machine learning laboratory only |
| **Date** | March 20, 2026 |

**2\. Executive summary**

The ML Laboratory Co-Scientist is a local-first product for running an end-to-end ML research loop: define a measurable goal, ingest problem context, triage literature, generate experiment ideas, build and run code locally, verify results, and prepare a competition submission or research note.

The MVP is intentionally narrower than a generalized co-scientist. It focuses on machine learning only, begins with Kaggle-style problems and an existing internal research corpus, and borrows the tight experimental discipline of autoresearch while adding missing layers: literature screening, structured evidence, protocolization, verification, and auditability.

The central product decision is metadata-first literature triage. The system should behave more like a human researcher: scan titles and abstracts at scale, fetch only the most relevant papers for full reading, and record why a paper was escalated. This keeps the system faster, cheaper, and more faithful to real research practice.

| Decision snapshot • Build a machine-learning laboratory first; generalized non-ML science workflows are explicitly deferred. • Optimize for a local, single-user, bounded-autonomy product rather than a cloud-scale autonomous lab. • Use Kaggle competitions plus the existing internal research corpus as the main evaluation environment. • Treat arXiv as a metadata-first source: titles and abstracts are reviewed first; full papers are fetched only for shortlisted items. • Measure success on verified experiments, reproducibility, and improved baselines—not on paper generation or flashy demos. • Require human approval for external side effects, especially competition rule acceptance, expensive runs, and Kaggle submissions. |
| :---- |

**3\. Background and problem statement**

Autonomous experimentation loops are useful once a problem is already packaged into a fixed metric, a fixed harness, and a small editable surface area. Real ML research is messier. Researchers must first understand the task, inspect the data, identify good baselines, discover prior art, decide which papers are actually worth reading, and design experiments that are both novel and reproducible.

Today, too much of that work is manual and poorly instrumented. Researchers bounce between Kaggle pages, notebooks, arXiv, internal notes, and experiment logs. Useful ideas get lost, repeated failures are not remembered, and literature review can devolve into brute-force PDF reading without a clear shortlist.

There is an opportunity to turn the research workflow itself into a product: a bounded ML laboratory that can intake a problem, map the local search space, propose and run credible experiments, and keep a clean evidence trail for every recommendation and result.

| Product opportunity Package the ML research workflow itself into a bounded co-scientist product: move from problem framing to verified experiment faster, with less manual thrash and a much better evidence trail. |
| :---- |

**4\. Vision, goals, and non-goals**

**Vision**

Become the best local co-scientist for ML practitioners: a system that can move from problem statement to verified experiment faster than a solo researcher, while staying grounded in evidence, reproducibility, and explicit human control.

**Goals**

**•** Reduce time from new ML problem to first successful baseline run.

**•** Create a reusable research loop that combines competition context, internal corpus knowledge, and arXiv discovery.

**•** Prefer title/abstract triage over brute-force full-paper ingestion and make every full-paper read an explicit, auditable decision.

**•** Generate multiple experiment hypotheses, not just one greedy path, and preserve failure memory as a first-class asset.

**•** Produce reproducible experiment records and valid Kaggle submission artifacts.

**•** Support a local, small-scale deployment model suitable for an individual researcher or very small team.

**Non-goals**

**•** General scientific domains such as wet-lab biology, chemistry, or physics workflows in v1.

**•** Autonomous publication or fully automated paper writing as a product goal.

**•** Bulk mirroring of the entire arXiv full-text corpus for the initial release.

**•** Large-scale multi-user orchestration, cluster scheduling, or enterprise access control.

**•** Operating without a measurable objective, bounded compute budget, or human approval gates.

**•** Replacing human judgment on competition rules, external communication, or final claims.

**5\. Users and jobs to be done**

Primary job to be done: when a researcher starts a new ML problem, the product should help them understand the task, map the relevant prior art, propose credible experiments, execute locally, and keep an auditable record of what was tried and what worked.

| Persona | Core need | Success signal |
| :---- | :---- | :---- |
| Solo ML researcher | Needs rapid baselines, a literature map, and a clean experiment log without setting up heavy infrastructure. | First baseline, first shortlist of papers, and first experiment queue in one session. |
| Research engineer | Needs runnable code, branch discipline, reproducible run artifacts, and clear failure history. | Can rerun any accepted experiment and understand why it was kept or rejected. |
| Applied science lead | Needs visibility into what the system tried, what it learned, and whether an improvement is credible. | Can review a concise evidence trail before green-lighting more compute or a submission. |
| Reviewer / approver | Needs hard gates around external actions and high-cost runs. | Can approve or reject submissions and riskier experiments without reading raw logs. |

**6\. Product principles and operating modes**

**Product principles**

**•** Local-first and bounded: the product must be useful on one machine with explicit budgets and no hidden background activity.

**•** Metadata before full text: the default literature workflow is title → abstract → shortlist → full paper.

**•** Evidence before generation: hypotheses must cite the specific evidence cards that motivated them.

**•** Verify before claim: improvements are not trusted until rerun, checked, and compared against a baseline.

**•** Human control for side effects: the system may prepare, but not silently execute, external writes.

**•** Failure memory matters: rejected ideas and broken runs should become reusable knowledge, not discarded noise.

**•** Narrow the domain early: optimize for ML lab workflows first, then generalize later from a strong core.

**Operating modes**

| Mode | Behavior | Why it matters |
| :---- | :---- | :---- |
| Assist | Suggests queries, papers, hypotheses, and experiment specs; human triggers all execution. | Lowest risk, best for early trust-building. |
| Execute | Runs approved local experiments within budget and records results automatically. | Default mode for the MVP after setup. |
| Submit | Prepares Kaggle-ready artifacts and can submit only after an explicit human approval step. | External side effects remain gated. |

**7\. MVP scope and release boundaries**

| In scope | Out of scope |
| :---- | :---- |
| Kaggle competition intake, baseline creation, experiment iteration, and submission preparation. | Generalized non-ML science adapters. |
| Internal research corpus indexing and retrieval. | Distributed cluster scheduling or cloud-native orchestration. |
| arXiv metadata retrieval and title/abstract screening. | Automated browsing and storage of all arXiv PDFs. |
| Selective full-paper fetching and note extraction for shortlisted papers. | Autonomous final publication or autonomous model release. |
| Evidence-backed hypothesis generation and protocol compilation. | Multi-user permissions and collaboration workflows. |
| Local sandbox execution with retries, logging, and verification. | Unbounded internet actions or rule acceptance on third-party platforms. |
| Experiment memory, failure memory, and a readable lab notebook. |  |

**Benchmark strategy**

The product will be evaluated on multiple Kaggle competition archetypes plus an internal corpus track. The goal is not to win a single competition but to prove that the loop works across different ML problem shapes.

| Track | Problem archetype | Why it exists |
| :---- | :---- | :---- |
| Kaggle Track A | Fast tabular / getting-started competition | Test quick baselines, feature ideation, and submission generation. |
| Kaggle Track B | Harder structured, text, or vision competition that still fits local compute | Test literature-guided iteration and experiment ranking. |
| Kaggle Track C | Code competition | Test notebook-based packaging, runtime constraints, and submission flow. |
| Internal Corpus Track | Existing ML research corpus plus held-out research questions | Test blended retrieval, reuse of prior internal work, and evidence quality. |

**Benchmark selection criteria**

**•** Each benchmark must have a clear target metric, a known submission format, and data that fits the local hardware envelope.

**•** The suite should cover at least one fast tabular problem, one higher-complexity task, and one code competition after the core loop is stable.

**•** The internal corpus track should include held-out questions so retrieval and recommendation quality can be evaluated, not just demonstrated.

**•** Benchmark selection should optimize for repeatability and product learning, not for chasing the newest or largest competition.

**MVP acceptance criteria**

**•** Given a Kaggle benchmark problem, the system can create a ResearchCharter, run a baseline, retrieve metadata-first literature results, execute at least one experiment cycle, and prepare a valid submission artifact.

**•** Given a research question against the internal corpus, the system can produce a shortlist of evidence-backed hypotheses and at least one runnable ExperimentSpec.

**•** For each benchmark cycle, the system can show which papers were screened at the title/abstract stage and which were escalated to full text.

**•** All accepted improvements have a RunRecord, a rerun or verification note, and a human-readable lab notebook entry.

**•** No external submission occurs without an explicit user approval event in the audit log.

**8\. End-to-end operating model**

The product should be thought of as a stateful research loop rather than a chatty collection of independent agents. A shared ResearchState stores the problem definition, literature evidence, experiment queue, run history, and approval states.

| Problem / Competition Goal | Research Charter \+ ResearchState | Metadata & Corpus Intake | Title / Abstract Triage | Shortlist Full-Text Reads | Hypothesis Portfolio | ExperimentSpec \+ Build | Local Execution \+ Verify | Submission / Report |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |

**Kaggle competition flow**

**1\.** User identifies a competition slug or chooses from a benchmark list.

**2\.** System ingests competition context: overview, data files, sample submission, target metric, and known constraints.

**3\.** Human accepts competition rules on Kaggle if not already done; the system records that this prerequisite is external and user-managed.

**4\.** System creates a ResearchCharter with objective, success metric, compute budget, stop conditions, and external-action policy.

**5\.** System builds or runs a baseline first and records that baseline as the anchor for later comparisons.

**6\.** System queries the internal corpus and arXiv metadata, then ranks paper cards using title and abstract only.

**7\.** System escalates only a small shortlist to full-paper reads, extracts evidence cards, and generates a hypothesis portfolio.

**8\.** System compiles top hypotheses into experiment specs, builds code changes, runs local experiments, and verifies any promising improvements.

**9\.** System prepares a submission candidate and leaderboard/context summary; human approves before any actual Kaggle submission.

**Internal research corpus flow**

**1\.** User defines an internal ML research question, target repository, and success metric.

**2\.** System creates a ResearchCharter and indexes the relevant project code, notes, papers, and experiment history.

**3\.** System retrieves internal corpus matches first, then supplements with arXiv title/abstract results if needed.

**4\.** System converts prior work into evidence cards, proposes hypotheses, and compiles them into experiment specs.

**5\.** System executes locally, reruns promising ideas, and generates a lab-note summary that can feed the next research cycle.

**9\. Literature discovery and title/abstract-first triage**

A central design choice in this product is to mimic how human researchers scan literature: broad title/abstract review first, selective deep reading second. The system should never assume that more PDFs equals better science.

**Triage policy**

**•** Default search sources are the internal corpus and arXiv metadata only.

**•** The ranking model should use task relevance, method match, novelty, recency when useful, and redundancy penalties.

**•** A full-paper fetch occurs only when the paper crosses a shortlist threshold, resolves a conflict, or is explicitly requested.

**•** The default budget should be conservative (for example, a small fixed cap or a percentage cap per cycle) and configurable.

**•** The system must preserve separate extraction modes: metadata-derived evidence is not the same as full-text-derived evidence.

**Paper lifecycle states**

| State | Meaning |
| :---- | :---- |
| Retrieved | Paper discovered from arXiv or the internal corpus, but not yet screened. |
| Title screened | Title reviewed and scored for likely relevance. |
| Abstract screened | Abstract reviewed; triage score updated and decision made on whether to shortlist. |
| Shortlisted | Paper selected for full-text fetch or deeper review. |
| Full-text read | Full paper downloaded or opened and converted into a richer evidence artifact. |
| Rejected / duplicate | Paper deemed not relevant enough, redundant, or outside scope. |

| Default shortlist rule The system should escalate only a small, high-value subset of papers to full text. A full-paper read must have a recorded reason such as strong relevance, conflict resolution, implementation detail need, or explicit human request. |
| :---- |

**10\. Human approval gates**

Human oversight is structural, not optional. The product should make it easy to collaborate with the researcher, especially around permissions, risk, and trust.

| Gate | Trigger | Required action |
| :---- | :---- | :---- |
| Competition access | Before data download or submission | Human accepts platform rules on Kaggle and records benchmark selection. |
| Full-text budget override | When shortlist exceeds configured paper budget | Human approves extra reads or tightens the search. |
| High-cost experiment | When estimated compute or runtime exceeds budget | Human approves or rejects the run. |
| External submission | Before any Kaggle submission | Human reviews evidence, run quality, and message. |
| Promoted claim | Before an improvement is marked accepted for reporting | Human or verifier confirms evidence is adequate. |

**11\. Functional requirements**

Requirements are grouped by product capability area. P0 items are required for the MVP. P1 items are important but may follow the initial narrow loop.

**Research Charter and Control Plane**

| ID | Requirement | Priority |
| :---- | :---- | :---- |
| FR-01 | The system must create a ResearchCharter before any autonomous action begins. | P0 |
| FR-02 | A ResearchCharter must include the objective, primary metric, dataset or competition, compute budget, stop conditions, and approval policy. | P0 |
| FR-03 | The system must refuse autonomous experimentation if no measurable success metric is available. | P0 |
| FR-04 | The orchestrator must maintain a persistent ResearchState and append-only audit log for every run. | P0 |
| FR-05 | The scheduler must support portfolio-style branching rather than a single greedy path. | P1 |

**Acceptance notes**

**•** A user can inspect the current ResearchCharter and see exactly what the system is trying to optimize.

**•** The system can resume work from a saved ResearchState after restart without losing run history.

**Source Intake and Literature Triage**

| ID | Requirement | Priority |
| :---- | :---- | :---- |
| FR-06 | The system must ingest internal corpus metadata and arXiv metadata into a common PaperCard format. | P0 |
| FR-07 | Title and abstract must be the default first-pass screening inputs. | P0 |
| FR-08 | Full-paper fetches must require either a shortlist threshold, a conflict-resolution need, or an explicit human request. | P0 |
| FR-09 | Every full-paper fetch must store a rationale, timestamp, and budget impact. | P0 |
| FR-10 | The system must deduplicate papers across arXiv, the internal corpus, and prior reads. | P1 |
| FR-11 | The user must be able to see why a paper was rejected, shortlisted, or escalated. | P1 |

**Acceptance notes**

**•** The first literature pass completes with PaperCards only, without requiring bulk PDF downloads.

**•** A reviewer can inspect the shortlist and understand why each paper was escalated.

**Hypothesis Portfolio and Review**

| ID | Requirement | Priority |
| :---- | :---- | :---- |
| FR-12 | The system must generate multiple HypothesisCards per research cycle, not just a single proposal. | P0 |
| FR-13 | Each HypothesisCard must cite one or more supporting EvidenceCards. | P0 |
| FR-14 | A reviewer or critic step must attempt to invalidate weak or redundant hypotheses before execution. | P0 |
| FR-15 | The portfolio manager must rank hypotheses by expected information gain, feasibility, and risk. | P1 |
| FR-16 | The user must be able to pin, reject, or edit hypotheses before execution. | P1 |

**Acceptance notes**

**•** At least one cycle can produce a ranked hypothesis portfolio with explicit supporting evidence.

**•** Weak or duplicate ideas can be filtered before compute is spent.

**Protocol Compilation, Build, and Execution**

| ID | Requirement | Priority |
| :---- | :---- | :---- |
| FR-17 | Every approved hypothesis must be compiled into an ExperimentSpec before code generation. | P0 |
| FR-18 | ExperimentSpec must include variables, controls, baseline, metrics, stop criteria, and required artifacts. | P0 |
| FR-19 | The system must run a baseline before judging any improvement. | P0 |
| FR-20 | The builder must create local code changes in a versioned workspace or branch. | P0 |
| FR-21 | The execution lab must run code in an isolated local environment with time and memory limits. | P0 |
| FR-22 | The system must capture logs, artifacts, and structured metrics for every run. | P0 |
| FR-23 | The system must retry fixable execution failures up to a configurable maximum retry count. | P1 |

**Acceptance notes**

**•** A successful run produces a RunRecord with command, status, metrics, and artifact paths.

**•** A failed run still produces a useful RunRecord and updates failure memory.

**Verification, Submission, and Reporting**

| ID | Requirement | Priority |
| :---- | :---- | :---- |
| FR-24 | Promising runs must be rechecked before being promoted to accepted results. | P0 |
| FR-25 | The system must include basic leakage and validation checks before submission preparation. | P0 |
| FR-26 | The system must generate Kaggle-compliant submission artifacts when a competition workflow is active. | P0 |
| FR-27 | Kaggle submissions must require explicit user approval. | P0 |
| FR-28 | The system must retrieve and store submission history and leaderboard context when available. | P1 |
| FR-29 | The reporting layer must generate a readable lab notebook entry for each completed cycle. | P1 |

**Acceptance notes**

**•** A human can approve a submission candidate based on a concise report rather than raw logs.

**•** Accepted results are clearly distinguished from tentative ones.

**Memory, Governance, and Safety**

| ID | Requirement | Priority |
| :---- | :---- | :---- |
| FR-30 | The system must store failure memory and rejected ideas as first-class records. | P0 |
| FR-31 | Every external action must be logged with actor, timestamp, and approval state. | P0 |
| FR-32 | The product must expose configurable budgets for compute, full-paper reads, and external actions. | P0 |
| FR-33 | The system must respect source-specific policies and rate limits for external platforms. | P0 |
| FR-34 | The system must never silently accept competition rules, publish artifacts, or claim verified improvements without evidence. | P0 |
| FR-35 | The user must be able to export the complete audit trail for a research cycle. | P1 |

**Acceptance notes**

**•** A reviewer can reconstruct what the system did, why it did it, and which actions were human-approved.

**•** Rate limiting and budget caps prevent accidental over-harvesting or runaway experimentation.

**12\. Non-functional requirements**

| ID | Area | Requirement |
| :---- | :---- | :---- |
| NFR-01 | Local-first operation | The MVP must run on a single machine with optional single-GPU acceleration and usable CPU fallback for lighter flows. |
| NFR-02 | Reproducibility | Every run must record code version, environment, seed, inputs, and metric outputs sufficient for rerun. |
| NFR-03 | Observability | The system must surface queue state, current experiment, last failure, and budget burn-down. |
| NFR-04 | Safety and permissions | External writes require explicit approval and must be auditable. |
| NFR-05 | Data hygiene | Competition data, internal notes, and source metadata must remain separated and traceable. |
| NFR-06 | Performance | Initial title/abstract triage should complete quickly enough to preserve an interactive research loop. |
| NFR-07 | Cost control | Budgets for experiments, retries, and full-paper reads must be configurable per research cycle. |
| NFR-08 | Usability | A researcher should understand what the system is doing without reading code or raw XML feeds. |

**13\. Core data model**

The product should standardize around a small number of durable objects. This creates a shared language across retrieval, generation, execution, and reporting.

| Object | Purpose | Required fields (illustrative) |
| :---- | :---- | :---- |
| PaperCard | Metadata-first unit for discovery and triage. | source, paper\_id, title, abstract, authors, date, categories, links, triage\_score, triage\_reason, read\_state |
| EvidenceCard | Structured claim or method summary extracted from metadata or full text. | claim, source\_refs, applicability, limitations, confidence, extraction\_mode |
| HypothesisCard | Candidate idea linked to the evidence that motivates it. | hypothesis, rationale, expected\_gain, novelty\_note, supporting\_evidence\_ids, risks |
| ExperimentSpec | Runnable specification that bridges idea and code. | baseline, variables, controls, metric, stop\_conditions, artifacts\_required, submission\_impact |
| RunRecord | Execution and result artifact. | commit\_id, command, environment, seed, status, metrics, errors, artifact\_paths, kept\_or\_rejected\_reason |
| SubmissionRecord | External action bundle for Kaggle. | competition, file\_or\_notebook\_ref, version, message, approval\_state, submission\_status, scores |

| ResearchState requirement ResearchState should hold the active charter, paper cards, evidence cards, hypothesis portfolio, experiment queue, run history, failure memory, submission records, budgets, and approval states. |
| :---- |

**14\. Success metrics and evaluation plan**

The MVP should be judged on whether it creates a credible, repeatable research loop. Product learning is more important than leaderboard theatrics.

| Metric | Definition | MVP target |
| :---- | :---- | :---- |
| Research charter completeness | Runs with objective, primary metric, constraints, and stop conditions recorded | 100% |
| Useful-paper precision@10 | Human-rated relevance of the top 10 title/abstract results | ≥ 60% in benchmark suite |
| Full-text fetch ratio | Full papers fetched ÷ papers retrieved in a cycle | ≤ 20% default budget |
| Shortlist quality | Fully read papers later cited in EvidenceCards or ExperimentSpecs | ≥ 70% |
| Valid run rate | Completed runs ÷ queued runs after first repair pass | ≥ 80% |
| Rerun reproducibility rate | Promising runs that reproduce within tolerance | ≥ 90% |
| Baseline improvement rate | Benchmark tracks with at least one verified improvement over baseline | ≥ 2 of 3 Kaggle tracks |
| Submission prep success | Approved candidates that generate valid competition artifacts | 100% |
| Time to first baseline | From accepted problem to first successful baseline run on benchmark hardware | \< 60 minutes |

**15\. Risks and mitigations**

| Risk | Failure mode | Mitigation |
| :---- | :---- | :---- |
| Leaderboard overfitting | The system chases public leaderboard gains that do not generalize. | Use local validation, track public/private score drift, and treat submissions as one signal rather than ground truth. |
| Data leakage | Generated features or validation schemes accidentally leak target information. | Add a leakage checker, dataset-specific validation templates, and human review before submission. |
| Hallucinated prior art | The system cites papers inaccurately or overstates claims. | Force EvidenceCards, record source mode (metadata/full-text), and require verification before promoting claims. |
| PDF over-harvesting | The system downloads too many papers and behaves unlike a researcher. | Enforce metadata-first triage, shortlist budgets, and source-specific rate limits. |
| Irreproducible improvements | A run looks better once but cannot be reproduced. | Rerun accepted candidates and store environments, seeds, and artifacts. |
| Compute blowouts | Local hardware is saturated by too many experiments or too-large models. | Require explicit budgets, queue caps, and cost estimation before approval. |
| Competition rule mistakes | The system prepares an invalid submission or ignores platform rules. | Keep human rule acceptance external and summarize constraints in the ResearchCharter. |
| Trust erosion | Users cannot tell why the system made a recommendation. | Make evidence, hypotheses, and approval states visible in the product UI/CLI. |

**16\. Roadmap and immediate next deliverables**

| Phase | Focus | Exit / output |
| :---- | :---- | :---- |
| Phase 0 | Planning and contracts | Finalize PRD, select benchmark suite, define ResearchState schema, and agree on local MVP boundaries. |
| Phase 1 | Local single-user MVP | Competition intake, metadata-first literature triage, baseline runs, ExperimentSpec generation, local execution, and lab notebook. |
| Phase 2 | Portfolio and verification hardening | Better hypothesis ranking, rerun verification, failure memory, and stronger submission/report workflows. |
| Phase 3 | Code competition support | Notebook-based competition packaging, runtime-aware experiment planning, and stronger competition adapters. |
| Phase 4 | Generalization planning | Use lessons from the ML lab to define adapter interfaces for other scientific domains. |

**Next documents to produce**

**•** A local small-scale reference architecture and recommended tech stack.

**•** A benchmark selection sheet covering Kaggle tracks and internal corpus tasks.

**•** JSON schemas for ResearchCharter, PaperCard, EvidenceCard, HypothesisCard, ExperimentSpec, and RunRecord.

**•** A thin CLI or notebook workflow spec for the first user-facing interface.

**17\. Open questions**

**•** Should the first local MVP use one foundation model with role prompts, or separate models for retrieval, coding, and review?

**•** How much of the internal research corpus should include code, notebooks, and experiment logs versus papers and notes only?

**•** What is the minimum acceptable verification standard before the system can mark a result as accepted?

**•** Should code competitions be part of the first benchmark wave or a second release once standard submissions are stable?

**•** How will the team define a 'useful paper' for retrieval evaluation in a way that is repeatable across benchmarks?

**•** How much human editing of hypotheses and ExperimentSpecs should be supported in the first interface?

**•** Do we want the first UI to be primarily CLI-first, notebook-first, or a minimal local web app?

**•** What level of offline arXiv metadata mirroring is worth the complexity for the MVP?

**Appendix A. External platform assumptions used in this PRD**

These assumptions are included so the PRD remains grounded in how the surrounding platforms actually work today.

**•** arXiv provides public metadata access via its API and supports bulk metadata harvesting via OAI-PMH; metadata includes fields such as title and abstract. The PRD therefore treats metadata-first retrieval as the default arXiv integration path.

**•** arXiv asks legacy API users to limit request rate and not serve PDFs from their own infrastructure unless licensing permits. The PRD therefore avoids default bulk PDF mirroring and emphasizes linking back to arXiv and fetching only shortlisted papers.

**•** Kaggle’s official CLI supports listing competitions, downloading competition data, making submissions, viewing submission history, and retrieving leaderboard information. The PRD assumes those actions can be wrapped in a competition adapter.

**•** Kaggle requires users to join a competition and accept rules on the website before downloading data or submitting. The PRD therefore treats rule acceptance as a human-managed prerequisite, not an automated agent action.

**•** Kaggle code competitions support notebook-based submission flows, which is why code-competition packaging is a distinct roadmap phase.

**•** Karpathy’s autoresearch demonstrates the power of a baseline-first, fixed-metric experiment loop on a constrained task. The PRD extends that idea with literature triage, protocol compilation, verification, and governance layers.