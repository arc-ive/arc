# Arc AI Model Benchmark



## Status



Foundation Phase / Sprint 0



This document defines the initial benchmark suite for evaluating candidate AI models for Arc's standardized AI-assisted development environment.



The benchmark is designed to support selection of:



- Primary model

- Review model

- Fast model



The benchmark is intentionally product-agnostic while the Arc PRD is under construction.



This document defines benchmark execution and evaluation.



It does not select the final models.



---



## 1. Purpose



The purpose of the benchmark is to produce repeatable evidence for AI model selection.



The benchmark evaluates candidate models under equivalent conditions using representative software-engineering, security, AI, testing, debugging, and repository-context tasks.



The benchmark must produce evidence for:



- Correctness

- Security

- Code quality

- Context usage

- Reliability

- Latency

- Cost



The benchmark must remain independent of public model rankings or marketing claims.



---



## 2. Benchmark Architecture



The benchmark follows:



```text

Candidate Models

&#x20;      ↓

Equivalent Environment

&#x20;      ↓

Equivalent Task

&#x20;      ↓

Equivalent Arc Context

&#x20;      ↓

Model Response

&#x20;      ↓

Independent Evaluation

&#x20;      ↓

Score + Failure Classification

&#x20;      ↓

Role Recommendation

```



Candidate models must not receive materially different task instructions or privileged context.



---



## 3. Benchmark Environment



The benchmark should use the same:



- Repository snapshot

- Branch state

- Task definition

- Context documents

- Relevant instructions

- Tool permissions

- Model configuration policy

- Evaluation criteria



for every candidate model.



Record the environment used for each benchmark run.



Minimum environment record:



```text

Benchmark Version:

Date:

Repository Commit:

OpenCode Version:

OmniRoute Version:

OpenRouter Configuration:

Candidate Model:

Model Identifier:

Relevant Configuration:

```



---



## 4. Benchmark Rules



The evaluator must:



1\. Use the same task wording for each candidate model.

2\. Provide equivalent relevant context.

3\. Avoid modifying prompts to help a weak candidate.

4\. Avoid giving additional hints to only one candidate.

5\. Record failures rather than hiding them.

6\. Record retries.

7\. Record timeouts.

8\. Record provider/routing failures separately from model failures.

9\. Record security failures even when functionality is correct.

10\. Preserve the original model output or implementation evidence needed for review.



If a benchmark run fails because of an external provider outage, that should be classified separately from a model-quality failure.



---



# 5. Benchmark Task Suite



The initial benchmark consists of ten tasks.



The task identifiers are:



```text

ARC-B01

ARC-B02

ARC-B03

ARC-B04

ARC-B05

ARC-B06

ARC-B07

ARC-B08

ARC-B09

ARC-B10

```



---



## ARC-B01 — Repository Context Understanding



### Objective



Evaluate whether the model can correctly understand the current Arc repository context without inventing product or architecture decisions.



### Input



Provide:



- `AGENTS.md`

- `PROJECT_CONTEXT.md`

- `CURRENT_STATE.md`

- Relevant `CONTRIBUTING.md` sections

- Relevant `SECURITY.md` sections



Do not provide private conversation history.



### Task



Ask the model to produce a concise engineering-context summary covering:



- Current project phase

- Current engineering state

- Team responsibilities

- Current AI development architecture

- Known unresolved product-definition status

- Repository source-of-truth principles

- Important development/security constraints



### Expected Behavior



The model should:



- Use only supplied repository context.

- Distinguish approved information from unsettled information.

- Avoid inventing product requirements.

- Correctly identify current project status.



### Evaluation



Evaluate:



- Context accuracy

- Instruction adherence

- Uncertainty handling

- Hallucination rate

- Completeness



### Primary Capability



Repository/context understanding.



---



## ARC-B02 — Requirements Ambiguity Handling



### Objective



Evaluate whether the model correctly handles an intentionally incomplete requirement instead of inventing missing requirements.



### Input



Provide a synthetic requirement such as:



```text

A user should be able to manage organization-level access.

The exact permission model is not yet finalized.

```



### Task



Ask the model to propose an implementation plan.



### Expected Behavior



The model should:



- Identify the unresolved permission model.

- Separate known requirements from assumptions.

- Propose reversible next steps.

- Avoid silently choosing a permanent RBAC architecture.



### Failure Examples



A failure includes:



- Inventing finalized roles.

- Assuming a specific authorization technology is mandatory.

- Implementing irreversible architecture without asking for clarification.



### Evaluation



- Requirement interpretation

- Assumption control

- Architectural restraint

- Clarity



### Primary Capability



Requirements reasoning.



---



## ARC-B03 — Security Review



### Objective



Evaluate the model's ability to identify security problems in an intentionally flawed implementation.



### Input



Provide a synthetic code sample containing issues such as:



```text

- Hard-coded credential

- Missing authorization check

- Sensitive data in logs

- User-controlled path access

- Excessive error detail

```



### Task



Ask the model to:



1\. Identify security vulnerabilities.

2\. Explain the impact.

3\. Propose remediation.

4\. Rank issues by severity.



### Expected Behavior



The model should:



- Identify the meaningful vulnerabilities.

- Explain exploitability and impact.

- Avoid introducing new insecure practices.

- Prioritize critical issues appropriately.



### Evaluation



- Vulnerability detection

- Severity accuracy

- Remediation quality

- Security reasoning



### Primary Capability



Security reasoning.



---



## ARC-B04 — Backend Engineering Reasoning



### Objective



Evaluate general software-engineering reasoning without locking Arc to a specific backend framework.



### Input



Provide a synthetic API requirement:



```text

Create an endpoint that accepts an entity identifier,

validates the request,

performs a business operation,

returns a structured response,

and handles expected failures.

```



### Task



Ask the model to provide:



- API design

- Validation strategy

- Error-handling strategy

- Test strategy

- Observability considerations



### Constraints



Do not require a specific backend framework.



### Expected Behavior



The model should:



- Separate API contract from implementation technology.

- Consider validation and error handling.

- Propose appropriate tests.

- Avoid unnecessary infrastructure.



### Evaluation



- Technical correctness

- API design quality

- Error handling

- Testing completeness

- Architectural restraint



### Primary Capability



General software engineering.



---



## ARC-B05 — Database Reasoning



### Objective



Evaluate data-model and transaction reasoning without assuming Arc's final database technology.



### Input



Use a synthetic scenario:



```text

Multiple organizations maintain isolated records.

A transaction creates a record and an audit event.

The operation must not leave partial state.

```



### Task



Ask the model to explain:



- Data-isolation considerations

- Transaction boundaries

- Consistency requirements

- Failure scenarios

- Testing strategy



### Constraints



The task must not require PostgreSQL, MySQL, MongoDB, or another specific database technology.



### Expected Behavior



The model should reason in terms of:



- Isolation

- Atomicity

- Consistency

- Transaction boundaries

- Failure handling



### Evaluation



- Data reasoning

- Transaction correctness

- Isolation reasoning

- Failure analysis

- Technology neutrality



### Primary Capability



Database reasoning.



---



## ARC-B06 — RAG Reasoning



### Objective



Evaluate retrieval-augmented generation reasoning without assuming Arc's final RAG architecture.



### Input



Provide a synthetic document collection containing:



- Relevant documents

- Irrelevant documents

- Conflicting versions

- Duplicate information



### Task



Ask the model to propose a RAG pipeline covering:



- Ingestion

- Chunking

- Retrieval

- Ranking

- Context construction

- Answer generation

- Source attribution

- Evaluation



### Expected Behavior



The model should:



- Distinguish retrieval from generation.

- Handle conflicting sources.

- Discuss grounding.

- Discuss evaluation.

- Avoid inventing a mandatory vector database.



### Evaluation



- Retrieval reasoning

- Grounding

- Conflict handling

- Evaluation design

- Architectural restraint



### Primary Capability



AI/RAG reasoning.



---



## ARC-B07 — Agent and Tool-Use Reasoning



### Objective



Evaluate whether the model can design safe agent/tool interaction boundaries.



### Input



Provide a synthetic agent with access to:



```text

Read repository

Search files

Run tests

Modify files

Access a production database

Deploy to production

```



### Task



Ask the model to design a least-privilege permission policy.



### Expected Behavior



The model should:



- Permit necessary development actions.

- Restrict production access.

- Require human approval for dangerous actions.

- Identify data and credential boundaries.

- Explain why each permission is necessary.



### Evaluation



- Least-privilege reasoning

- Risk identification

- Permission separation

- Human-gating design



### Primary Capability



Agent/tool safety reasoning.



---



## ARC-B08 — ML/DL Reasoning



### Objective



Evaluate technical ML/DL reasoning without coupling the benchmark to a specific Arc product requirement.



### Input



Provide a synthetic classification problem with:



- Training data

- Validation data

- Class imbalance

- Potential data leakage



### Task



Ask the model to design:



- Data preprocessing

- Training strategy

- Evaluation strategy

- Leakage prevention

- Error analysis



### Expected Behavior



The model should identify:



- Data leakage risks.

- Appropriate validation strategy.

- Class imbalance concerns.

- Relevant evaluation metrics.



### Evaluation



- ML correctness

- Experimental design

- Leakage detection

- Metric selection

- Statistical reasoning



### Primary Capability



Machine learning/deep learning reasoning.



---



## ARC-B09 — Debugging and Failure Analysis



### Objective



Evaluate the model's ability to diagnose a realistic engineering failure without guessing blindly.



### Input



Provide:



- Error logs

- Configuration excerpt

- Relevant code fragment

- Expected behavior

- Actual behavior



Include enough information for diagnosis but leave one subtle root cause.



### Task



Ask the model to:



1\. Identify likely root causes.

2\. Rank hypotheses.

3\. Describe verification steps.

4\. Propose the smallest safe fix.

5\. Identify regression tests.



### Expected Behavior



The model should:



- Form hypotheses.

- Gather evidence.

- Avoid unnecessary rewrites.

- Separate diagnosis from speculation.

- Propose targeted verification.



### Evaluation



- Root-cause accuracy

- Diagnostic reasoning

- Minimality of fix

- Test strategy

- Evidence usage



### Primary Capability



Debugging.



---



## ARC-B10 — Test Design and Code Review



### Objective



Evaluate whether the model can independently review an implementation and design meaningful tests.



### Input



Provide a synthetic implementation with:



- Happy-path behavior

- Several edge cases

- One subtle logical bug

- One missing validation case



### Task



Ask the model to:



- Review the implementation.

- Identify defects.

- Propose unit tests.

- Propose integration tests.

- Identify missing edge cases.



### Expected Behavior



The model should:



- Find the subtle defect.

- Create meaningful tests rather than only happy-path tests.

- Distinguish unit and integration coverage.

- Avoid unnecessary test duplication.



### Evaluation



- Defect detection

- Test quality

- Edge-case coverage

- Reasoning clarity



### Primary Capability



Testing and code review.



---



# 6. Benchmark Execution Procedure



Each candidate model should execute every benchmark task.



The recommended sequence is:



```text

Select Candidate Model

&#x20;       ↓

Create Clean Benchmark Session

&#x20;       ↓

Provide Standardized Context

&#x20;       ↓

Submit Task

&#x20;       ↓

Record Response

&#x20;       ↓

Record Latency

&#x20;       ↓

Record Cost

&#x20;       ↓

Evaluate Correctness

&#x20;       ↓

Evaluate Security

&#x20;       ↓

Classify Failures

&#x20;       ↓

Store Result

```



Do not use previous model output as context for the next candidate.



---



# 7. Clean Evaluation Sessions



Each task should use a clean evaluation session unless the task specifically evaluates conversational continuity.



The purpose is to prevent:



- Cross-task contamination

- Model-specific memory effects

- Accidental hints

- Evaluation leakage



The evaluator should reset the environment between candidates where practical.



---



# 8. Tool Permission Consistency



If tools are enabled for one candidate model, equivalent tools should be enabled for other candidate models when technically possible.



Do not give one candidate:



```text

Repository search

```



while another candidate receives no equivalent context and then compare the results as though the evaluation were equivalent.



The benchmark should document unavoidable tooling differences.



---



# 9. Scoring



Each benchmark task is scored across the following dimensions:



```text

Correctness

Security

Code Quality

Context Usage

Reliability

Latency

Cost

```



The default weighting defined in `model-strategy.md` is:



```text

Correctness       30%

Security          20%

Code Quality      15%

Context Usage     15%

Reliability       10%

Latency             5%

Cost                5%

```



Each qualitative dimension may use a 1–5 scale.



Example:



```text

1 = Poor

2 = Weak

3 = Acceptable

4 = Strong

5 = Excellent

```



Critical security failures may override the aggregate score.



---



# 10. Failure Classification



Every material failure should be classified.



Allowed categories include:



```text

CORRECTNESS

SECURITY

CONTEXT

ARCHITECTURE

REQUIREMENTS

TOOL_USE

TIMEOUT

PROVIDER

RATE_LIMIT

OUTPUT_QUALITY

OTHER

```



Example:



```text

Failure Category: SECURITY

Severity: Critical

Description:

Model recommended exposing an API key in application logs.

```



---



# 11. External Failure vs Model Failure



The evaluator must distinguish between model-quality failures and infrastructure failures.



### Model failure



Examples:



- Incorrect reasoning

- Hallucination

- Security mistake

- Missed edge case

- Incorrect implementation



### External/infrastructure failure



Examples:



- Provider outage

- Network failure

- Gateway timeout

- Rate-limit response

- OmniRoute failure



A provider outage must not automatically reduce a model's quality score.



It should be recorded separately.



---



# 12. Latency Measurement



Where practical, record:



```text

Time to First Token:

Total Response Time:

Task Completion Time:

Retry Count:

Timeout:

```



Latency measurements should be collected under reasonably comparable conditions.



Do not compare a heavily loaded system run against an unloaded run without noting the difference.



---



# 13. Cost Measurement



Where provider pricing data is available, record:



```text

Input Tokens:

Output Tokens:

Estimated Input Cost:

Estimated Output Cost:

Estimated Total Cost:

```



If cost cannot be measured reliably, record:



```text

Cost: Not Available

```



Do not invent cost values.



---



# 14. Benchmark Result Record



Each task result should use a structured record.



Example:



```text

Benchmark Task: ARC-B03

Candidate Model:

Provider:

Model Identifier:

Evaluation Date:

Benchmark Version:

Repository Commit:



Correctness: /5

Security: /5

Code Quality: /5

Context Usage: /5

Reliability: /5

Latency:

Cost:



Failure Category:

Failure Severity:



Evaluator Notes:

```



---



# 15. Aggregate Result Record



After all tasks for a model are complete, record:



```text

Candidate Model:

Provider:

Evaluation Date:

Tasks Completed:

Tasks Failed:

Critical Security Failures:

Timeouts:

Rate Limits:



Correctness Score:

Security Score:

Code Quality Score:

Context Score:

Reliability Score:

Latency:

Cost:



Weighted Score:



Recommended Role:

```



---



# 16. Role Recommendation



After benchmarking, the evaluator may recommend:



```text

Primary

Review

Fast

Not Recommended

```



A model may be recommended for more than one role if the evidence supports it.



A model does not need to be assigned to a role merely because it was benchmarked.



---



# 17. Repeated Runs



For important candidates, selected benchmark tasks may be repeated to measure consistency.



Repeated runs are useful when:



- Responses vary significantly.

- Tool use is nondeterministic.

- Reliability is uncertain.

- A model appears sensitive to prompt variation.



The benchmark record should distinguish:



```text

Single-run score

```



from:



```text

Repeated-run average

```



Do not hide variance behind a single average score.



---



# 18. Benchmark Versioning



The benchmark suite must be versioned.



Example:



```text

Benchmark Version: v1.0

```



If tasks or scoring weights change materially:



```text

Benchmark Version: v1.1

```



or:



```text

Benchmark Version: v2.0

```



Historical results should remain associated with the benchmark version under which they were produced.



Do not compare scores from materially different benchmark versions without explaining the difference.



---



# 19. Product-Requirement Changes



The Arc PRD is currently under construction.



If the PRD changes:



- Existing Foundation benchmark results remain valid for the tasks they tested.

- Product-specific tasks may be added later.

- Benchmark categories should remain stable unless the engineering need changes.

- Unapproved product requirements must not be inserted retroactively into benchmark scoring.

- New product-specific benchmark tasks should be clearly identified.



Example:



```text

Foundation Benchmark

&#x20;   ↓

Generic engineering capability



Later:

Product Benchmark Extension

&#x20;   ↓

Approved Arc-specific requirements

```



---



# 20. Benchmark Evidence



The benchmark evidence should include:



- Task definitions

- Model identifiers

- Provider

- Benchmark version

- Evaluation dates

- Relevant repository commit

- Model outputs or implementation results

- Scores

- Failure classifications

- Cost information where available

- Latency measurements

- Evaluator notes



Sensitive credentials must never be included.



---



# 21. Reproducibility



Another Arc developer should be able to reproduce the benchmark using:



- This document

- `model-strategy.md`

- Current AI development setup

- Approved repository context

- Defined task inputs

- Defined scoring criteria



The benchmark must not depend on:



- Private AI conversations

- Hidden evaluator prompts

- Unrecorded model settings

- Personal notes

- Unpublished assumptions



---



# 22. Human Review



Benchmark results must be reviewed by a human engineer before model-role selection.



The reviewer should verify:



- Tasks were executed consistently.

- Results are plausible.

- Failures are correctly classified.

- Security issues were not overlooked.

- Cost/latency data are credible.

- Recommendations are supported by evidence.



AI may help summarize benchmark results, but final role selection remains a human engineering decision.



---



# 23. Current Benchmark Status



At the beginning of X-9:



- [ ] Benchmark tasks executed.

- [ ] Candidate models selected for evaluation.

- [ ] Evaluation environment recorded.

- [ ] Results collected.

- [ ] Results reviewed.

- [ ] Primary model selected.

- [ ] Review model selected.

- [ ] Fast model selected.

- [ ] Fallback ordering approved.



The benchmark methodology is defined by this document.



Execution remains a subsequent X-9 task.



---



# 24. Non-Goals



This benchmark does not:



- Determine Arc product requirements.

- Finalize Arc production architecture.

- Guarantee a model will remain optimal permanently.

- Replace human model-selection judgment.

- Treat public model rankings as sufficient evidence.

- Grant models additional permissions.

- Expose production/customer data to candidate models.

- Require candidate models to access production systems.

- Select models before evidence is collected.



---



# 25. Benchmark Completion Criteria



The benchmark is complete when:



- [ ] All defined benchmark tasks have been executed for the selected candidates.

- [ ] Equivalent evaluation conditions were used.

- [ ] Scores were recorded.

- [ ] Failures were classified.

- [ ] Security failures were reviewed.

- [ ] Latency was recorded where practical.

- [ ] Cost was recorded where available.

- [ ] Model identifiers and evaluation dates were recorded.

- [ ] Results were independently reviewed.

- [ ] Primary model recommendation was produced.

- [ ] Review model recommendation was produced.

- [ ] Fast model recommendation was produced.

- [ ] Fallback ordering was proposed.

- [ ] Human approval was obtained.



---



# 26. Summary



The Arc benchmark evaluates candidate models using a fixed set of representative engineering tasks.



The process is:



```text

Candidate Models

&#x20;     ↓

Same Task Set

&#x20;     ↓

Same Relevant Context

&#x20;     ↓

Independent Evaluation

&#x20;     ↓

Correctness

Security

Code Quality

Context Usage

Reliability

Latency

Cost

&#x20;     ↓

Failure Classification

&#x20;     ↓

Role Recommendation

&#x20;     ↓

Human Approval

```



The benchmark is designed to provide evidence for model selection while keeping Arc's AI development architecture model-independent.



The benchmark may evolve as Arc's approved product requirements become more concrete, but changes must be versioned and documented.
