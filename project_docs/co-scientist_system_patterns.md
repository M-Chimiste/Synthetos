**System Patterns**

**ML Laboratory Co-Scientist**  ·  Architecture baseline for the local ML laboratory MVP

| Role | The Architect |
| :---- | :---- |
| **Product** | ML Laboratory Co-Scientist |
| **Status** | Revised Working Draft |
| **Scope** | Local small-scale ML laboratory MVP centered on scoped research problems, internal research memory, and external literature sources. |
| **Last Updated** | 2026-03-21 |

| Revision focus in this update Re-centered the architecture on scoped ML research problems instead of a Kaggle-first workflow. Added task-scoped context assembly so operators do not receive the entire project state by default. Made literature handling metadata-first and arXiv HTML-first, with PDFs used only when HTML is insufficient. Shifted routine experimentation toward automation within policy, with live telemetry and user intervention controls. Made a phase-1 UI part of the baseline architecture rather than a later add-on. Strengthened reporting, historical comparison, and failure-memory patterns so results stay legible and reusable. Clarified the local-first stack around PostgreSQL, an arXiv metadata mirror, and a GPU-capable execution backplane. |
| :---- |

**1\. Purpose**

This document defines the canonical system architecture for the ML Laboratory Co-Scientist. It answers five questions clearly: what the system is made of, how the major parts relate, which architectural patterns keep the product reliable and explainable, which default technology choices shape the MVP, and which decisions are intentionally deferred so the build stays narrow and practical.

This document is architecture-first. It sets the system shape, component boundaries, data flow, and major decisions with rationale. It does not attempt to pin exact packages, local commands, or environment setup in detail; those belong in tech\_context.md.

The product scope assumed here is a local-first, single-user ML laboratory MVP with metadata-first literature triage, bounded autonomy, explicit policies, and a research loop that can pursue scoped problems across internal and external sources without brute-forcing full-text ingestion.

**2\. Architecture Summary**

The ML Laboratory Co-Scientist should be built as a stateful research operating system, not as a loose swarm of chatting agents.

The core architectural decision is simple: the system runs as a set of typed operators over a shared ResearchState, backed by durable storage, explicit policy, and an append-only audit trail.

The product is organized around three loops:

1. Explore — ingest the scoped problem, screen literature, synthesize evidence, and maintain a ranked hypothesis portfolio.  
2. Experiment — compile hypotheses into executable ExperimentSpecs, modify code in isolated workspaces, and run local experiments.  
3. Verify — rerun or replicate results, check for leakage or invalid comparisons, update failure memory, and prepare human-readable finding packets.

Everything in the architecture exists to support those loops without losing provenance, reproducibility, human control, or operator context discipline.

**3\. System Design Principles**

**3.1 Local-first by default**

The system must run on a single developer machine without requiring cluster orchestration, cloud queues, or multi-tenant infrastructure. Remote services may be used for model inference or metadata retrieval, but the product must remain usable as a bounded local lab.

**3.2 Shared state over agent conversation**

The system should not depend on hidden prompt history as its memory. Durable state lives in structured records, artifacts, and audit events. Operator inputs are assembled from that state, rather than recovered from freeform chat history.

**3.3 Context discipline is mandatory**

The product must not broadcast the entire project state to every model. Each operator receives only the evidence, failures, protocol fragments, or run summaries relevant to its task. This keeps token cost bounded, reduces drift, and makes reasoning traces easier to inspect.

**3.4 Metadata before full text**

Literature discovery follows the same funnel a careful researcher would use: title plus abstract together, shortlist, full text only when justified, and evidence extraction last. For arXiv, the system should prefer HTML or other machine-readable full text before falling back to PDF parsing.

**3.5 Deterministic core, probabilistic edge**

LLMs are useful for synthesis, ideation, critique, and report drafting. They should not own bookkeeping, experiment tracking, approval logic, or policy enforcement.

**3.6 Evidence before hypothesis, hypothesis before code**

The product should not jump directly from a task description to generated code. Ideas must be grounded in evidence, then compiled into an ExperimentSpec, then executed.

**3.7 Reproducibility is a first-class feature**

Every accepted claim must be traceable to code, data, prompts, metrics, runtime environment, and approval decisions.

**3.8 Automate routine work, reserve humans for leverage**

Most low-risk experimentation and hypothesis-disproving work should run automatically within policy. Human approval is reserved for high-cost, high-risk, external, or budget-overriding actions. The user must still be able to observe, pause, abort, redirect, and annotate the lab in real time.

**3.9 Narrow now, extensible later**

The architecture should generalize cleanly, but only after a strong ML lab core exists. Generalized science adapters are deferred; ML is the primary domain model.

**4\. Top-Level System Shape**

**4.1 Runtime topology**

| Layer | Contains | Why it exists |
| :---- | :---- | :---- |
| User Surface | Local web UI, CLI, rendered reports | The UI is part of phase 1\. It surfaces telemetry, approvals, finding packets, and intervention controls. |
| Control Plane / API | Research state API, scheduler entry points, policy checks, telemetry endpoints | One entry point for creating cycles, queueing work, approving actions, and inspecting current state. |
| Worker / Operator Pool | Intake, literature triage, synthesis, ideation, protocol compile, build, execute, verify, report | Operators consume task-scoped context packs and emit durable results. |
| Durable State | PostgreSQL, pgvector, audit events, DB-backed queue | This is the system of record for research state, jobs, policies, and lineage. |
| Artifact Store | Local filesystem | Runs, reports, literature caches, notes, patches, and exports remain inspectable on disk. |
| Execution Backplane | Git worktrees plus GPU-capable containers | Generated code runs in isolated workspaces and containers with resource controls and GPU passthrough. |
| External / Local Adapters | arXiv metadata, arXiv HTML/PDF, internal corpus, datasets, models, git, container runtime | All external systems sit behind adapters so the core remains testable and vendor-agnostic. |

**4.2 Architectural stance**

* The system is not built around agent-to-agent message passing.  
* It is built around typed records, explicit state transitions, operator execution with durable inputs and outputs, append-only audit events, isolated experiment workspaces, and policy-checked approvals.  
* This is what makes the lab debuggable, restartable, and explainable.

**5\. Core Architectural Patterns**

**5.1 Shared ResearchState as source of truth**

Each research cycle is represented by a durable ResearchState. Operators do not own hidden memory. They read from and write to the same canonical record set.

A ResearchState should reference, at minimum:

* ResearchCharter and ProblemProfile  
* Literature search sessions and PaperCards  
* EvidenceCards and contradiction signals  
* Hypothesis portfolio and ExperimentSpec queue  
* RunRecord history, VerificationReports, and FailureMemory entries  
* FindingPackets, budget state, approval state, and audit events

Why this pattern exists: it makes the system restartable, keeps work inspectable without replaying prompt history, supports deterministic testing against stored state, and prevents agent memory drift from becoming hidden product logic.

**5.2 State machine orchestration**

The lab should be implemented as a state machine over a research cycle, not as a freeform conversational workflow.

| created  \-\> chartered  \-\> baseline\_ready  \-\> literature\_screened  \-\> shortlist\_ready  \-\> portfolio\_ready  \-\> execution\_queued  \-\> running  \-\> verifying  \-\> report\_ready  \-\> closedcross-cutting states: approval\_pending, paused, blocked, aborted, failed |
| :---- |

Not every cycle will visit every state, but transitions must be explicit and auditable. An operator may only move the cycle to an allowed next state and must emit the event that explains why.

Why this pattern exists: it prevents uncontrolled branching, makes retries explicit, supports pause and resume behavior, and simplifies approvals and failure handling.

**5.3 Event-sourced audit trail**

The product should keep an append-only audit log of domain events. This is not full event sourcing for every read model, but it is a durable trail for every meaningful action.

Example event types include research\_charter\_created, paper\_title\_abstract\_screened, paper\_shortlisted, fulltext\_fetch\_approved, hypothesis\_generated, experiment\_spec\_created, run\_started, run\_failed, run\_verified, failure\_postmortem\_created, report\_ready, and user\_intervened.

The audit trail must also be materialized into user-facing timelines, activity feeds, and report sections so a human can quickly understand what happened without reading raw logs.

Why this pattern exists: it lets humans reconstruct what happened, supports debugging and future analytics, preserves approval history, and provides a foundation for lab notebooks and reports.

**5.4 Ports and adapters / hexagonal architecture**

External systems must sit behind adapters. Core research logic should not know the details of arXiv retrieval, model providers, dataset sources, git operations, or the container runtime.

The core should depend on interfaces such as:

* ResearchProblemAdapter  
* LiteratureAdapter  
* CorpusAdapter  
* DatasetAdapter  
* EmbeddingAdapter  
* LLMAdapter  
* ExecutionAdapter  
* TelemetryAdapter  
* ReportAdapter

Why this pattern exists: it makes the product testable with fixtures and mocks, contains external API churn, keeps business rules independent from vendors, and lets the system act more like a reusable lab assistant than a benchmark-specific script.

**5.5 Metadata-first retrieval funnel**

The literature subsystem must preserve the difference between metadata-only evidence, HTML full-text evidence, PDF or figure-driven evidence, and implementation details extracted from deeper reads.

Papers should move through lifecycle states rather than being treated as simply ingested or not ingested.

| metadata\_retrieved  \-\> title\_abstract\_screened  \-\> shortlisted  \-\> html\_fetched  \-\> pdf\_fetched\_if\_needed  \-\> evidence\_extracted |
| :---- |

Pattern rules:

* Title and abstract are scored together, not independently, because paper titles can be clever or underspecified.  
* Recency is an explicit ranking feature alongside semantic relevance and problem fit.  
* Full-text fetch is an escalation with a recorded reason, not the default path.  
* For arXiv, HTML or other machine-readable full text is preferred before PDF parsing.

Allowed escalation reasons: high triage score, conflict resolution, implementation detail needed for experiment design, explicit human request, or missing and insufficient HTML.

Why this pattern exists: it matches real researcher behavior, reduces compute and storage waste, improves evidence quality by making escalation deliberate, and keeps the system from becoming a brute-force PDF crawler.

**5.6 Portfolio search, not greedy search**

The system should maintain a ranked portfolio of hypotheses and experiments rather than following one single proposal to completion before considering alternatives.

This means multiple hypotheses can survive review, multiple ExperimentSpecs can be queued, failure memory informs future ranking, and the scheduler can pick the next experiment by expected value rather than order of creation.

Suggested ranking factors include expected information gain, implementation feasibility, estimated runtime or cost, novelty relative to internal and external prior work, risk of invalid evaluation, and fit to the current problem profile.

Why this pattern exists: science is not a linear greedy optimization process, the first decent idea is rarely the best branch, and portfolio management helps conserve scarce local compute.

**5.7 Ephemeral workspaces with durable lineage**

Every proposed experiment should execute in its own isolated workspace, ideally backed by a git worktree or equivalent branch directory.

Each run should capture source commit or parent branch, generated patch or diff, problem profile, runtime image or environment identifier, prompt and model identifiers used during generation, seeds, dataset hash or cache reference, produced artifacts, and metrics.

Why this pattern exists: it keeps experiment code isolated, makes diffs reviewable, allows exact replay of accepted results, and prevents one run from corrupting another.

**5.8 Containerized execution sandbox with GPU passthrough**

Generated or modified code must not execute directly on the host environment.

The execution pattern for the MVP should be:

* Build or reuse a problem-specific base image.  
* Mount dataset cache read-only where possible.  
* Mount the workspace read-write and an artifact directory for outputs.  
* Disable network by default and grant it only through policy.  
* Enforce time, memory, disk, and GPU usage limits.  
* Capture stdout, stderr, exit code, resource usage, and container metadata.

Why this pattern exists: generated code is untrusted, research runs must be isolated from the control plane, resource caps are necessary on a local workstation, and deterministic reruns need stable environments.

**5.9 Deterministic verification before promotion**

Verification should be its own subsystem, not an optional postscript. Before a run is promoted from promising to accepted, the system should perform deterministic checks appropriate to the task.

* Rerun or replicate the experiment when randomness or instability is possible.  
* Compare against the declared baseline and relevant prior internal runs.  
* Run leakage checks, split validation checks, and metric sanity checks.  
* Verify required artifacts, reports, and schemas are present and parseable.  
* Prepare a concise reviewer summary describing whether the improvement looks robust, tentative, or likely spurious.

LLMs may summarize or interpret verification results, but they do not replace verification itself.

Why this pattern exists: most bad scientific claims fail on validation details, not creativity, and accepted results must be reproducible and auditable.

**5.10 Policy engine for budgets and approvals**

A separate policy layer should decide whether an operator may proceed. Low-cost, low-risk experiments may run automatically within policy. High-cost, high-risk, external, or budget-overriding actions should pause for approval.

The policy layer must handle compute budget ceilings, full-text read ceilings, allowed problem profiles, network access permissions, automatic execution classes, high-cost run approvals, model-routing policy, and approvals for any external write or publication step.

Why this pattern exists: it keeps safety and budget logic out of prompt text, prevents accidental overreach by operator code, and makes human collaboration structural rather than advisory.

**5.11 Derived graph views, not a graph database in v1**

The system should store core entities in relational tables and derive graph views when needed. Useful graph views include citation relationships, evidence-to-hypothesis links, hypothesis-to-experiment lineage, repeated method families, contradiction clusters, and recency overlays.

Why this pattern exists: the core product needs durability and queryability more than graph-native storage, relational plus vector storage is simpler to build and operate locally, and most useful graph views can be materialized from structured records later.

**5.12 Live telemetry and intervention surface**

The lab must stream its status while it works. Users should not need to poll raw logs or wait for a final report to understand what is happening.

* Expose queued, running, blocked, failed, and completed work in real time.  
* Stream resource usage, metric snapshots, audit activity, and pending approvals.  
* Allow the user to pause, abort, reprioritize, redirect search scope, and attach notes while work is in progress.

Why this pattern exists: automation only feels trustworthy when the user can inspect and intervene, especially during long-running research loops.

**5.13 Task-scoped context assembly**

Operators should be invoked with a context pack tailored to the task, not with the entire project state. A ContextBuilder should select the relevant evidence slice, recent failures, open questions, protocol fragments, or run summaries required for the next operator.

Rules for the pattern:

* Do not broadcast all state to all models.  
* Version and attach the context pack used by each operator to its operator report.  
* Treat retrieval of additional context as an explicit, logged action.  
* Prefer compact structured state over long narrative summaries where possible.

Why this pattern exists: it respects model context limits, lowers cost, reduces irrelevant prompt contamination, and keeps operator reasoning grounded in what was actually provided.

**6\. Recommended MVP Stack Shape**

This section defines the canonical architectural stack for the MVP. It sets the intended shape without yet pinning exact package versions or local startup commands.

| Area | Default choice | Why this is the default |
| :---- | :---- | :---- |
| Core language | Python | Best fit for ML workflows, orchestration, scientific tooling, and model-driven code generation. |
| API / control plane | FastAPI-style Python service | Good balance of typed models, async support, and local deployment simplicity. |
| UI surface | Local web dashboard plus CLI | Phase 1 needs live telemetry, approvals, intervention, and a readable report surface. |
| Durable state | PostgreSQL | Strong transactional model, row locking, JSON support, and a solid base for queueing and audit history. |
| Vector retrieval | pgvector in PostgreSQL | Keeps vector search close to canonical state and avoids a second search service in v1. |
| Lexical retrieval | PostgreSQL full-text search | Good enough for metadata-first search over arXiv metadata, internal corpus, and notes. |
| Artifact store | Local filesystem | Fits local-first deployment and keeps artifacts inspectable. |
| Job queue | Database-backed queue | Simpler than a separate queue service in a single-user MVP and keeps jobs auditable. |
| Execution backplane | GPU-capable Docker containers | Safest practical local sandbox for generated code and ML workloads. |
| Workspace isolation | Git worktrees | Clean per-experiment code isolation with clear lineage. |
| Telemetry | DB-backed event log plus WebSocket or SSE stream | Supports a live UI without introducing a second real-time platform early. |
| LLM access | Provider-agnostic gateway with role-based model routing | Allows different models for planning, coding, critique, and evaluation across local and hosted providers. |
| Embeddings | Provider-agnostic embedding adapter | Supports future swaps between hosted and local embeddings. |
| Config | File-based project config plus environment overrides | Keeps local operation explicit and reproducible. |
| Reporting | Rendered Markdown plus HTML viewer | Readable on day one and more useful than raw markdown files alone. |

**6.1 Why PostgreSQL instead of SQLite for the canonical path**

SQLite is attractive for simplicity, but the MVP needs durable multi-table state, append-only audit history, queue semantics with safe locking, vector retrieval, concurrent reads while workers run, and room for a full arXiv metadata mirror. A local PostgreSQL instance is a better long-term default than starting with SQLite and migrating later.

**6.2 Why not Redis/Celery in the first pass**

The product is local-first and single-user. A DB-backed queue is simpler to reason about than a separate queue service and aligns better with the audit-trail requirement. A heavier workflow engine can be introduced later only if the local scheduler becomes a real bottleneck.

**6.3 Why not Elasticsearch or OpenSearch in the first pass**

The first release is not a web-scale search product. Title and abstract screening across a local arXiv metadata mirror, targeted external queries, and an internal corpus can be handled with hybrid lexical and vector retrieval in PostgreSQL. A separate search cluster would increase operational complexity before it adds product value.

**6.4 Why the UI belongs in phase 1**

The UI is not decoration. It is the control surface for telemetry, approvals, intervention, and report review. A research lab that automates experimentation without a readable surface will feel opaque and harder to trust.

**7\. Major Bounded Contexts**

**7.1 Control Plane**

Responsibility — create and update the ResearchCharter, expose APIs and CLI commands, coordinate approvals, enqueue work, and expose current lab state.

Owns — research-cycle lifecycle, policy checks at entry points, and operator scheduling triggers.

Does not own — deep search logic, experiment code execution, or literature parsing internals.

**7.2 Research Memory**

Responsibility — persist all durable entities and relationships, support retrieval over papers, evidence, hypotheses, runs, and notes, and maintain audit history and job records.

Primary record types — ResearchCharter, ResearchState, ProblemProfile, PaperCard, EvidenceCard, HypothesisCard, ExperimentSpec, RunRecord, VerificationReport, FailureMemoryEntry, FindingPacket, ApprovalEvent, and DomainEvent.

Pattern note — this is the system of record. All other components treat it as authoritative.

**7.3 Source Intake**

Responsibility — ingest scoped problem definitions and datasets, ingest internal corpus metadata and selected content, maintain a local arXiv metadata mirror in PostgreSQL, run incremental metadata syncs, and fetch deeper paper content only when escalated.

Sub-adapters — ProblemDefinitionAdapter, DatasetSourceAdapter, InternalCorpusAdapter, ArxivMetadataMirrorAdapter, ArxivSearchAdapter, ArxivHTMLAdapter, and ArxivPDFAdapter.

Pattern note — full-text retrieval is physically separated from metadata retrieval so budget policy can control it directly.

**7.4 Literature Intelligence**

Responsibility — score title plus abstract together, deduplicate across sources, produce shortlist recommendations, extract structured evidence from metadata or full text, and preserve source provenance and escalation rationale.

Primary outputs — screened PaperCards, EvidenceCards, shortlist decisions, contradiction signals, redundancy signals, and recency-aware relevance scores.

Pattern note — this subsystem prepares the evidence surface; it does not decide final experiment execution.

**7.5 Ideation and Review**

Responsibility — generate multiple candidate hypotheses from evidence, critique hypotheses for novelty, weakness, redundancy, and likely failure modes, and rank the portfolio before protocol compilation.

Primary outputs — HypothesisCards with cited evidence, review notes, and a ranked queue for experiment design.

Pattern note — generator and critic are operator roles over shared state, not autonomous personas with private memory.

**7.6 Protocol Compiler**

Responsibility — convert approved hypotheses into executable ExperimentSpecs, define controls, baselines, metrics, artifacts, stop conditions, and expected outputs, and reject under-specified ideas before code generation begins.

Primary outputs — validated ExperimentSpecs, required artifact schemas, and run preflight checklists.

Pattern note — this is the bridge between an interesting idea and a valid experiment.

**7.7 Build and Execution Lab**

Responsibility — create isolated workspaces, apply code changes, prepare runtime images or environments, execute runs within policy limits, and capture outputs into RunRecords.

Sub-components — WorkspaceManager, PatchBuilder, ExecutionRunner, ArtifactCollector, and ResourceMonitor.

Pattern note — the build system assumes that generated code is fallible and untrusted.

**7.8 Verification**

Responsibility — compare runs to baselines and prior internal work, rerun or replicate promising experiments, run leakage and evaluation checks, and determine whether a run can be promoted.

Primary outputs — VerificationReports, promotion or rejection decisions, and structured failure-memory updates.

Pattern note — promotion is a verification outcome, not a generation outcome.

**7.9 Reporting and Lab Notebook**

Responsibility — generate concise human-readable summaries, produce notebook-style entries per cycle, and explain literature screening, selected papers, experiment results, historical comparison, and open questions.

Outputs — cycle summaries, experiment notebooks, finding packets, activity-feed digests, and exportable review bundles.

Pattern note — the reporting layer consumes verified state. It is not the place where truth is decided.

**7.10 Approvals and Policy**

Responsibility — enforce approval requirements, block disallowed actions, persist approval history, and expose pending approvals to the user.

Examples — full-text paper budget override, high-cost experiment approval, network-enabled run approval, and approval for any external publication, submission, or write.

Pattern note — policy and approval checks should be reusable across operators, not re-implemented inside each one.

**7.11 Telemetry and Intervention**

Responsibility — stream current status, resource usage, metric changes, pending approvals, and report readiness to the UI and CLI.

User controls — pause, abort, reprioritize, redirect research scope, and attach notes or guidance while work is active.

Pattern note — visibility and intervention are part of the product, not an afterthought.

**8\. Primary Data and Lineage Model**

The following lineage path should be treated as canonical:

| PaperCard / CorpusRecord / PriorRunRecord    \-\> EvidenceCard        \-\> HypothesisCard            \-\> ExperimentSpec                \-\> RunRecord                    \-\> VerificationReport                        \-\> FindingPacket or AcceptedFinding |
| :---- |

**8.1 Key entity roles**

**ResearchCharter —** Defines the objective, scope, success metric, budget, stop conditions, and approval policy.

**ResearchState —** Represents the current state of the cycle and connects all major records.

**ProblemProfile —** Defines the concrete ML problem shape: dataset, metric, artifact contract, runtime envelope, and constraints.

**PaperCard —** Represents a paper or internal document at the screening layer, including source type, metadata, lifecycle state, triage score, and recency.

**EvidenceCard —** Represents a structured claim, method, limitation, result, contradiction, or implementation insight derived from a source.

**HypothesisCard —** Represents a candidate research direction grounded in one or more EvidenceCards.

**ExperimentSpec —** Defines the concrete experimental plan: variables, controls, baseline, expected outputs, stop conditions, and artifact contract.

**RunRecord —** Represents a concrete execution attempt, including environment, commit lineage, logs, metrics, artifacts, and status.

**VerificationReport —** Represents post-run validation, rerun status, leakage checks, historical comparison, and promotion decision.

**FailureMemoryEntry —** Represents a classified failure or non-improving result with a short postmortem and follow-on recommendations.

**FindingPacket —** Represents the human-readable report bundle for a result: evidence links, metrics, novelty summary, and optional external-action payload.

**ApprovalEvent —** Represents a human decision allowing or denying a gated action.

**DomainEvent —** Represents any append-only audit event emitted by the system.

**8.2 Important lineage rules**

* A HypothesisCard must cite one or more EvidenceCards.  
* An ExperimentSpec must reference the HypothesisCard it operationalizes.  
* A RunRecord must reference the exact ExperimentSpec and workspace lineage used.  
* Every experiment must end with a recorded verification outcome or failure classification.  
* Every failed or non-improving run should produce a FailureMemoryEntry with a short postmortem.  
* A promoted claim must reference at least one VerificationReport.  
* Any external write or publication step must reference both a FindingPacket and an ApprovalEvent.

**9\. Operator Contract Pattern**

Operators should be implemented as typed units of work rather than arbitrary prompt calls.

| Operator(context\_pack, config)  \-\> OperatorResult(       state\_patch,       emitted\_events,       created\_artifacts,       approvals\_requested,       next\_actions,       operator\_report     ) |
| :---- |

**9.1 Operator design rules**

* Operators should be idempotent where practical.  
* Operators must emit durable outputs before downstream work is queued.  
* Prompts and model identifiers must be versioned and referenced in operator outputs.  
* Operator reports must be inspectable by a human.  
* Policy must be checked before side effects occur.  
* Context packs must be built explicitly and kept bounded to what the operator needs.  
* Different operator roles may use different models behind the same gateway.

**9.2 Why this matters**

This pattern keeps the system composable without turning it into an opaque agent loop. It also makes unit testing, replay, and operator-level debugging much easier.

**10\. Critical Workflow Patterns**

**10.1 Scoped research problem intake pattern**

| user defines research direction or scoped problem  \-\> control plane creates ResearchCharter  \-\> ProblemDefinitionAdapter resolves datasets, baseline, metrics, and constraints  \-\> dataset and cache access are checked  \-\> ProblemProfile is created  \-\> baseline experiment is generated and run |
| :---- |

Important rule: benchmark-style tasks are only one subtype of ProblemProfile. The architecture is centered on scoped research problems, not on any single external benchmark platform.

**10.2 Literature triage pattern**

| problem context \+ baseline context  \-\> targeted query planning  \-\> query local arXiv metadata mirror \+ internal corpus \+ configured external sources  \-\> dedupe  \-\> joint title\_abstract scoring with recency features  \-\> shortlist ranking  \-\> optional HTML fetch with reason  \-\> PDF fallback if HTML is insufficient  \-\> evidence extraction |
| :---- |

Important rule: full-text reads are budgeted and reasoned. The system must be able to explain why each escalated paper was worth deeper reading and why HTML or PDF was required.

**10.3 Hypothesis to experiment pattern**

| EvidenceCards  \-\> hypothesis generation  \-\> critique and redundancy filtering  \-\> portfolio ranking  \-\> scheduler or user selects a candidate  \-\> protocol compiler creates ExperimentSpec  \-\> preflight checks  \-\> build workspace and patch  \-\> execute |
| :---- |

Important rule: no direct paper-insight-to-code shortcut should bypass ExperimentSpec.

**10.4 Verification and promotion pattern**

| completed run  \-\> baseline comparison  \-\> historical internal comparison  \-\> metric sanity checks  \-\> rerun or replicate  \-\> leakage and validation checks  \-\> VerificationReport  \-\> promoted finding or failure-memory update |
| :---- |

Important rule: outside scores or benchmark standings are useful context, but they do not replace local verification and historical comparison.

**10.5 Report and external action pattern**

| verified run  \-\> FindingPacket builder  \-\> human-readable results and novelty report  \-\> human approval request if external action is needed  \-\> optional external adapter call  \-\> store receipt, response, and provenance |
| :---- |

Important rule: report\_ready and external\_action\_executed are separate states. Every finding packet should explain what changed, why it matters, how it compares with prior work, and what to test next.

**11\. Storage Pattern**

**11.1 System of record**

The system of record should be PostgreSQL for structured state, queueing, audit events, and vector references, plus the local filesystem for large artifacts and cached external assets.

**11.2 Filesystem layout pattern**

| /data  /artifacts    /runs    /reports    /findings    /literature      /html      /pdfs      /notes  /cache    /arxiv    /datasets    /embeddings  /workspaces  /exports |
| :---- |

**11.3 Artifact philosophy**

Artifacts should be treated as durable evidence, not temporary scratch by default. This includes run logs, metric snapshots, generated patches, literature notes, extracted evidence summaries, rendered reports, and failure postmortems.

**11.4 Why filesystem first**

A local filesystem is the simplest inspectable artifact store for a single-user lab. It is easy to browse, easy to back up, and easy to replace with object storage later if needed.

**12\. Search and Retrieval Pattern**

**12.1 Hybrid retrieval**

The retrieval system should combine lexical search over title, abstract, authors, tags, and internal notes; vector search over semantic embeddings; and structured filters such as source type, problem relevance, recency, prior read state, and failure relation.

**12.2 Separate indexes for separate evidence layers**

At minimum, there should be distinct logical search views for title and abstract metadata, HTML or full-text notes, internal corpus documents, and historical run reports plus failure memory.

**12.3 Why separate views matter**

A metadata match is not the same as a full-text implementation-detail match. The retrieval layer must preserve those differences so the system does not overstate how deeply it has read a paper or how directly a source supports an experiment.

**13\. Execution Pattern**

**13.1 Problem profiles**

Each supported research task should compile into a ProblemProfile that defines dataset location, offline validation metric, optional external artifact schema, expected runtime envelope, allowed hardware profile, artifact contract, and known constraints. This keeps problem-specific behavior out of the core orchestration logic.

**13.2 Workspace lifecycle**

| create isolated worktree  \-\> apply patch  \-\> preflight  \-\> execute in sandbox  \-\> collect artifacts  \-\> generate postmortem summary  \-\> archive workspace metadata  \-\> optionally keep patch for review |
| :---- |

**13.3 Preflight pattern**

Before execution, the system should run a lightweight preflight that checks config completeness, referenced files, metric parser availability, artifact schema understanding, runtime image readiness, resource estimate fit, and whether required GPU access fits policy.

**13.4 Failure classification**

Run failures should be classified rather than lumped together. Useful classes include build failure, dependency failure, out-of-memory or resource limit, runtime exception, metric-parse failure, invalid artifact output, policy rejection, and harness mismatch. This is necessary for useful failure memory.

**13.5 Base image strategy**

The system may keep a small set of reusable base images for common ML stacks, but most runtime images should be assembled on demand from the current ProblemProfile. That keeps the baseline lightweight while still supporting problem-specific environments.

**14\. Verification Pattern**

**14.1 Minimum verification bundle for ML research tasks**

* Baseline comparison on the declared offline metric.  
* Comparison to prior internal runs and reproduced literature baselines where available.  
* Confirmation that the evaluation split and schema are the intended ones.  
* Configured checks for target leakage, label contamination, or dataset misuse.  
* Required artifacts present, parseable, and linked to the run.  
* A rerun or replicate note explaining how stability was checked.  
* A reviewer summary describing whether the result is robust, tentative, or likely spurious.

**14.2 Historical work comparison policy**

The system should preserve the distinction between baseline improvement, improvement relative to prior internal experiments, comparison against literature claims or reproductions, and optional external benchmark outcomes when available later. This keeps the lab from optimizing to a single visible score and makes novelty claims more honest.

**14.3 Failure memory and postmortem requirement**

Every failed or non-improving experiment should emit a structured failure record and a short reflective postmortem. The scheduler may use that information to downgrade similar branches, refine a hypothesis, or trigger new literature search aimed at the failure mode that was observed.

**15\. Human Interaction Pattern**

The product should feel like a research control tower, not a black box.

**15.1 Preferred interaction model**

* Use the local web UI to inspect current state, live telemetry, reports, runs, and pending approvals.  
* Keep the CLI for power users, scripts, and direct operator control.  
* Link every surfaced recommendation to its evidence and lineage.

**15.2 Required approval surfaces**

* Extra full-text reads beyond budget.  
* Expensive or long-running experiments.  
* Network-enabled runs.  
* Promotion of headline claims.  
* Any external publication, submission, or other irreversible write.

**15.3 Required live controls**

* Pause or abort running work.  
* Reprioritize queued experiments.  
* Adjust research scope or search constraints.  
* Attach human notes or guidance.  
* Resume from a paused or blocked state.

**15.4 Explainability pattern**

* A shortlisted paper should show its title-plus-abstract score, recency, and escalation reason.  
* A hypothesis should show its supporting evidence and critique summary.  
* A promoted run should show its baseline comparison, historical comparison, and verification status.

**15.5 Reporting surface**

Rendered markdown is acceptable in the first pass, but it must be viewable in the product through an HTML or equivalent rendered surface. Raw markdown files alone are not a sufficient reporting experience.

**16\. Repository and Folder Structure Pattern**

A practical repository shape for the MVP is:

| repo/  apps/    api/    worker/    web/    cli/  libs/    schemas/    core/    orchestration/    storage/    retrieval/    literature/    ideation/    protocols/    execution/    verification/    reporting/    telemetry/    adapters/      problems/      datasets/      arxiv/      corpus/      llm/      embeddings/      git/      container/  prompts/    literature/    ideation/    critique/    reporting/  configs/    problems/    policies/    prompts/  docs/context/  data/sample/  tests/    unit/    integration/    fixtures/  scripts/ |
| :---- |

**16.1 Structure rules**

* Canonical schemas should live in one place.  
* Adapters must not invert dependencies by importing core domain logic in the wrong direction.  
* Prompts are versioned assets, not hidden strings inside business logic.  
* Notebooks may support exploration, but they are not the system backbone.  
* Problem configs should live in files, not in prompt text.

**17\. Key Architectural Decisions (ADR Snapshot)**

**ADR-001 — Build the core in Python —** Python is the primary language for orchestration, adapters, and execution tooling because it aligns best with ML workflows and scientific tooling.

**ADR-002 — Use shared ResearchState instead of freeform agent memory —** Durable typed state is the system backbone because replayability, testing, and user trust depend on it.

**ADR-003 — Use task-scoped context packs rather than full-state prompts —** Each operator should see only the context it needs, which keeps token cost bounded and reduces prompt contamination.

**ADR-004 — Choose PostgreSQL plus pgvector as the canonical storage path —** Relational plus vector retrieval in one durable store supports state, queueing, vector search, and audits with fewer moving parts.

**ADR-005 — Use a database-backed job queue instead of Redis/Celery or a full workflow engine —** Jobs are persisted and claimed through the main database because this fits a local-first MVP with strong audit requirements.

**ADR-006 — Maintain a local arXiv metadata mirror —** A PostgreSQL-backed mirror of arXiv metadata should be part of the research memory and kept fresh with bulk and incremental sync.

**ADR-007 — Treat title plus abstract as the default literature surface, and prefer HTML before PDF —** This mirrors real researcher behavior, improves parseability, and avoids wasteful full-text crawling.

**ADR-008 — Ship a phase-1 web UI alongside the CLI —** Telemetry, approvals, intervention, and rendered reporting require a readable local interface from day one.

**ADR-009 — Execute generated code inside isolated GPU-capable containers and separate workspaces —** Generated code is untrusted and must run in reproducible, resource-constrained sandboxes.

**ADR-010 — Baseline first, always —** No experiment is judged without an explicit baseline anchor because false wins are otherwise too easy.

**ADR-011 — Verification is separate from generation, and every experiment gets tested —** Creative generation and scientific validation are different stages; every experiment needs an explicit recorded outcome.

**ADR-012 — Human approval is required for external writes and high-cost or high-risk actions —** Routine low-risk experiments may run automatically, but anything irreversible, external, or expensive should require approval.

**ADR-013 — Use research problem adapters for problem-specific behavior —** Problem logic must not leak into core orchestration because the lab should support multiple ML research task types cleanly.

**ADR-014 — Derive graph views instead of introducing a graph database in v1 —** Graph-native storage would add complexity before it adds enough product value.

**ADR-015 — Support both local and hosted models behind one gateway with role-based routing —** Different operators will likely benefit from different models for planning, coding, critique, and evaluation.

**18\. Explicit Anti-Patterns**

4. Agent swarm as architecture. Multiple LLM personas talking to each other without a strong state model is not the system design.  
5. Broadcasting the full project state to every model. Context must be scoped to the operator and task.  
6. Brute-force mirroring of arXiv full-text PDFs. Metadata-first retrieval is the default, with HTML preferred before PDF.  
7. Running generated code directly on the host machine. All experiment code runs through sandboxed execution.  
8. Using prompt text as policy logic. Budgets and approval rules must live in code and configuration.  
9. Treating any single visible score as the sole truth signal. Offline verification and historical comparison remain primary.  
10. Unplanned platform sprawl beyond the canonical local stack. PostgreSQL, a phase-1 frontend, and a GPU-capable execution backplane are intentional; adding extra services without clear product need is the anti-pattern.  
11. Jumping from hypothesis directly to a code patch without protocolization. ExperimentSpec is required.  
12. Using notebooks as the product backbone. Notebooks may support exploration, but durable system logic lives in the repo and runtime.

**19\. Evolution Path**

**Phase 1 — Local ML lab core**

* Single-user local runtime.  
* Phase-1 web UI plus CLI and live telemetry.  
* Problem adapters for a small set of ML task archetypes.  
* Internal corpus retrieval plus a local arXiv metadata mirror.  
* Metadata-first literature triage with HTML-first escalation.  
* Automated experiment execution, verification, and failure memory.

**Phase 2 — Better research memory and richer UI**

* Stronger contradiction mapping and cross-run reasoning.  
* Better portfolio ranking and queue management.  
* Richer collaboration features in the UI.  
* Reusable problem packs and stronger report exports.

**Phase 3 — Optional scale-up**

* Optional remote workers.  
* Object storage replacement for filesystem artifacts.  
* More advanced search and ranking models.  
* Support for additional research domains through new adapters.

The key rule is that scale should follow product truth, not lead it.

**20\. Current Defaults for tech\_context.md**

The following defaults should now be treated as the current architectural stance while tech\_context.md is written:

* Phase 1 includes a UI, not just an API and CLI.  
* The model gateway supports both local and hosted models from day one, with role-specific routing.  
* A notebook-packaging adapter is deferred until the core script-based research loop is stable.  
* The research memory should include a PostgreSQL-backed arXiv metadata mirror, refreshed by bulk and incremental sync, with targeted API search when needed.  
* The runtime may keep a few reusable base images, but most images should be assembled on demand from the current ProblemProfile.  
* Every experiment must receive an explicit recorded verification outcome.  
* Failure memory should be as structured as practical and should include a short postmortem that can trigger revised hypotheses or additional search.  
* Reports may start as rendered Markdown and HTML, but they must be viewable inside the product.

**20.1 Remaining open questions**

* Which frontend framework gives the cleanest local-first development path for the phase-1 UI?  
* What is the exact GPU runtime and quota model for the execution backplane on a single machine?  
* Which three ML problem packs should ship first?  
* How much internal code-repository ingest belongs in v1 versus later phases?  
* Which statistical checks should be mandatory by default for each initial problem family?

**21\. Recommended Next Step**

The next document should be tech\_context.md, derived from this architecture, and should make concrete decisions about local runtime setup, service startup model, package and dependency choices, environment-variable and config loading, PostgreSQL deployment, arXiv sync flow, container and GPU setup, model-provider strategy, coding standards, testing strategy, benchmark and problem configuration format, and the phase-1 UI stack.