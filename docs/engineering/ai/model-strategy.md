# Arc AI Model Strategy



## Status



Foundation Phase / Sprint 0



This document defines the model-selection strategy for the Arc AI-assisted development environment.



The objective is to select models by engineering role and measured performance rather than permanently coupling Arc to a single model.



This document does not permanently select specific models.



---



## 1. Purpose



Arc uses an abstraction between the coding-agent interface and downstream AI models.



The stable interface is:



```text

Developer

&#x20;   ↓

OpenCode

&#x20;   ↓

OmniRoute

&#x20;   ↓

OpenRouter

&#x20;   ↓

Configured Model Role

```



Model identities may change without changing the overall development workflow.



The initial model roles are:



- Primary

- Review

- Fast



Each role is selected based on documented evaluation rather than popularity or public leaderboard position alone.



---



## 2. Model Selection Principles



Model selection must follow these principles:



1\. Measure before standardizing.

2\. Keep model identifiers configurable.

3\. Evaluate models against representative engineering tasks.

4\. Use the same evaluation conditions for candidate models.

5\. Consider security as a first-class evaluation criterion.

6\. Consider context handling and repository understanding.

7\. Consider latency and cost.

8\. Record evaluation results and selection dates.

9\. Re-evaluate when a model is materially changed, deprecated, unavailable, or replaced.

10\. Never allow model selection to weaken Arc's security or permission boundaries.



---



## 3. Model Roles



### 3.1 Primary



The Primary model is used for higher-complexity engineering work.



Typical tasks:



- Feature implementation

- Complex debugging

- Multi-file reasoning

- Architecture exploration

- Difficult refactoring

- Repository-level engineering tasks



Evaluation emphasis:



- Correctness

- Reasoning quality

- Context handling

- Code quality

- Reliability

- Security

- Cost



---



### 3.2 Review



The Review model is used for independent critique.



Typical tasks:



- Code review

- Security review

- Architecture review

- Defect identification

- Edge-case identification

- Assumption checking



Evaluation emphasis:



- Critical reasoning

- Defect detection

- Security reasoning

- Ability to challenge an existing implementation

- Independence from the original implementation approach



The Review model does not replace human review.



---



### 3.3 Fast



The Fast model is used for low-complexity, high-frequency tasks.



Typical tasks:



- Documentation

- Small edits

- Simple test generation

- Routine transformations

- Lightweight repository queries

- Low-complexity fixes



Evaluation emphasis:



- Latency

- Cost

- Reliability

- Acceptable correctness



A Fast model must still meet the minimum security and quality requirements of the task.



---



## 4. Candidate Model Policy



Candidate models must remain externally configurable.



The repository must not hard-code a single permanent model identity.



The model strategy should therefore distinguish:



```text

Stable role

&#x20;   ↓

Configurable model identifier

```



rather than:



```text

Stable role

&#x20;   ↓

Permanent model

```



Candidate models may be changed because of:



- Benchmark results

- Cost

- Latency

- Availability

- Provider limits

- Reliability

- Context-window requirements

- Tool-use capability

- Security performance



A change of model does not automatically require an architecture change when the surrounding AI development architecture remains unchanged.



---



## 5. Benchmark Objectives



The benchmark must answer:



1\. Which candidate model is best suited to Primary work?

2\. Which candidate model is best suited to Review work?

3\. Which candidate model is best suited to Fast work?

4\. How consistently does each model perform?

5\. What are the cost and latency trade-offs?

6\. What security weaknesses or failure patterns appear?

7\. How well does each model use repository context?

8\. How does each model behave when requirements are ambiguous?



---



## 6. Benchmark Design Principles



The benchmark must be:



- Repeatable

- Comparable

- Documented

- Version-aware

- Security-aware

- Cost-aware

- Independent of marketing claims



Candidate models should receive equivalent tasks and equivalent context.



The benchmark should avoid changing the evaluation conditions in ways that unfairly favor one model.



---



## 7. Initial Benchmark Size



The initial benchmark should contain approximately 8–10 representative engineering tasks.



The exact task set may evolve.



The initial categories should cover:



- Backend/software engineering reasoning

- Database reasoning

- Security

- RAG reasoning

- Agent/tool-use reasoning

- Machine learning/deep learning reasoning

- Testing

- Debugging

- Repository/context understanding



Because the Arc product requirements are currently evolving, the initial benchmark should use product-agnostic or synthetic tasks rather than assuming unfinished product requirements are final.



After the approved PRD stabilizes, product-specific evaluation tasks may be added.



---



## 8. Benchmark Task Requirements



Every benchmark task should define:



- Task objective

- Input/context

- Expected output

- Constraints

- Evaluation criteria

- Expected engineering risks

- Relevant security considerations

- Test/evaluation method



A benchmark task must be sufficiently precise that multiple candidate models can be evaluated under equivalent conditions.



---



## 9. Context Consistency



Every candidate model must receive equivalent relevant project context.



Where a repository-context task is used, the benchmark should use the same:



- Repository snapshot

- Task specification

- Relevant documentation

- Applicable instructions

- Requirements

- Architecture context



The benchmark must not provide privileged context to one candidate model that is unavailable to another.



---



## 10. Evaluation Dimensions



Each candidate model should be evaluated using at least the following dimensions.



### 10.1 Correctness



Evaluate whether the response or implementation:



- Satisfies the task

- Produces technically valid results

- Handles relevant edge cases

- Avoids incorrect assumptions



---



### 10.2 Security



Evaluate whether the model:



- Avoids insecure implementations

- Respects secrets boundaries

- Respects authorization boundaries

- Recognizes data exposure risks

- Identifies security-sensitive edge cases



Security failures should be treated as significant even if the resulting implementation appears functionally correct.



---



### 10.3 Code Quality



Evaluate:



- Maintainability

- Readability

- Appropriate abstraction

- Dependency discipline

- Error handling

- Testability

- Consistency with repository conventions



---



### 10.4 Context Usage



Evaluate whether the model:



- Uses the relevant repository context

- Respects project instructions

- Identifies applicable requirements

- Identifies applicable ADRs

- Avoids contradicting repository documentation

- Avoids inventing missing project requirements



---



### 10.5 Latency



Measure the practical response time for the task.



Where possible, record:



- Time to first response

- Total task completion time

- Number of retries

- Timeout frequency



Latency should be evaluated relative to the model role.



---



### 10.6 Cost



Where cost data is available, record:



- Input cost

- Output cost

- Estimated task cost

- Total benchmark cost



Cost should not be considered independently of correctness and security.



---



## 11. Scoring Model



A benchmark may use a normalized scoring system.



Example:



```text

Correctness       30%

Security          20%

Code Quality      15%

Context Usage     15%

Reliability       10%

Latency             5%

Cost                5%

```



These weights are an initial benchmark proposal, not a permanent rule.



The team may adjust the weights after reviewing the first benchmark results.



Security-critical tasks may require additional gating regardless of aggregate score.



---



## 12. Failure Classification



Benchmark failures should be classified where possible.



Suggested categories:



```text

Correctness failure

Security failure

Context failure

Architecture violation

Requirement misunderstanding

Tool-use failure

Timeout

Provider failure

Rate-limit failure

Output-quality failure

```



This is more useful than relying only on a single numerical score.



---



## 13. Role Selection Rules



A model should be selected for a role only after considering:



- Benchmark performance

- Security behavior

- Reliability

- Cost

- Latency

- Context handling

- Current availability

- Tool-use compatibility



The highest aggregate score is not automatically the correct selection.



For example:



```text

Model A

Higher score

but significant security failures



Model B

Slightly lower score

but no critical security failures



→ Model B may be the safer role selection.

```



Human engineering judgment remains part of the selection process.



---



## 14. Model Assignment Record



Once benchmarking is completed, record:



```text

Evaluation Date:

Benchmark Version:

OpenCode Version:

OmniRoute Version:

OpenRouter Configuration:

Primary Model:

Review Model:

Fast Model:

Reasoning:

Known Limitations:

```



The assigned models should remain configurable.



---



## 15. Model Version Tracking



Evaluation results should record the model identifier used at evaluation time.



Where possible, also record:



- Provider

- Model version or revision

- Evaluation date

- Configuration

- Relevant model parameters



A benchmark result without the model identity and evaluation date is incomplete.



---



## 16. Re-evaluation Policy



Re-evaluation should be considered when:



- A model version materially changes

- A model is deprecated

- A provider changes availability

- Cost changes materially

- Reliability changes materially

- Rate limits change materially

- Benchmark performance degrades

- A significant new Arc requirement emerges

- A security issue is discovered



The goal is to keep model assignments evidence-based.



---



## 17. Fallback Strategy



OmniRoute may support model fallback when a selected model becomes temporarily unavailable.



Potential failure causes include:



- Rate limiting

- Timeout

- Provider outage

- Model availability failure

- Gateway failure



Fallback behavior must be:



- Configurable

- Deterministic

- Documented

- Observable

- Security-equivalent to the original route



Fallback must not silently switch to a model with materially different permissions or security assumptions.



---



## 18. Fallback Ordering



Fallback ordering should be configured explicitly.



For example:



```text

Primary Candidate A

&#x20;       ↓ failure

Primary Candidate B

&#x20;       ↓ failure

Primary Candidate C

```



The fallback order should be based on:



- Compatibility

- Reliability

- Security

- Availability

- Cost

- Quality



Fallback chains must not become uncontrolled lists of arbitrary models.



---



## 19. Fallback and Role Separation



Fallback must preserve the requested role.



For example:



```text

Primary role

&#x20;   ↓

Primary candidate A

&#x20;   ↓ failure

Primary candidate B

```



should not automatically become:



```text

Primary role

&#x20;   ↓

Fast model

```



unless the team has explicitly accepted that behavior.



This prevents unexpected quality degradation during fallback.



---



## 20. Benchmark Reproducibility



The benchmark procedure should be reproducible by another developer.



The repository should contain:



- Task definitions

- Evaluation instructions

- Scoring criteria

- Model identifiers

- Evaluation dates

- Result records

- Known limitations



The benchmark process should not depend on private AI conversations.



---



## 21. Product-Agnostic Benchmark Policy



While the Arc PRD remains under construction:



- Do not invent product requirements.

- Do not create benchmark tasks that assume unapproved modules.

- Do not evaluate models against unfinished architecture as if it were final.

- Prefer generic engineering tasks and synthetic examples.

- Clearly label assumptions.



After the PRD is approved, product-specific benchmark tasks may be added.



Existing benchmark results should not be discarded solely because product-specific tasks are later introduced.



---



## 22. Security Requirements



Model selection must never weaken the security boundaries defined in:



`SECURITY.md`



and:



`docs/engineering/ai/security.md`



The selected model must not receive broader access merely because it performs better.



Model quality and model permissions are separate concerns.



---



## 23. Human Review



Human engineers remain responsible for:



- Final model-role selection

- Security acceptance

- Architecture implications

- Reviewing benchmark conclusions

- Approving changes to the model strategy



AI may assist with benchmarking, but an AI-generated benchmark conclusion is not automatically an engineering decision.



---



## 24. Current Status



At the beginning of X-9:



- The AI development architecture is defined.

- OpenCode is installed and verified.

- OmniRoute is installed and verified.

- OpenRouter is configured and verified.

- End-to-end model routing has been demonstrated.

- Final Primary model is not selected.

- Final Review model is not selected.

- Final Fast model is not selected.

- Formal benchmark execution has not yet been completed.

- Final fallback ordering has not yet been approved.



Therefore, no specific model should yet be documented as the permanent Arc model for any role.



---



## 25. Model Strategy Completion Criteria



The model strategy is considered complete when:



- [ ] Benchmark procedure is documented.

- [ ] Approximately 8–10 representative tasks are defined.

- [ ] Candidate models are identified.

- [ ] Equivalent evaluation conditions are established.

- [ ] Correctness is evaluated.

- [ ] Security is evaluated.

- [ ] Code quality is evaluated.

- [ ] Context usage is evaluated.

- [ ] Latency is evaluated.

- [ ] Cost is evaluated.

- [ ] Results are recorded with model identifiers and dates.

- [ ] Primary role selection is documented.

- [ ] Review role selection is documented.

- [ ] Fast role selection is documented.

- [ ] Fallback behavior is documented.

- [ ] Human review of the selection is completed.



---



## 26. Non-Goals



This document does not:



- Permanently select a specific AI model before benchmarking.

- Replace human model-selection decisions.

- Define product requirements.

- Define the production AI architecture.

- Define production deployment.

- Grant additional AI permissions.

- Treat public benchmark rankings as sufficient evidence.

- Require every model to be used in production.

- Require a single provider forever.



---



## 27. Summary



Arc treats models as configurable implementations of stable engineering roles.



The stable abstraction is:



```text

Primary

Review

Fast

```



The model selection process is:



```text

Candidate Models

&#x20;     ↓

Equivalent Benchmark Tasks

&#x20;     ↓

Correctness

Security

Code Quality

Context Usage

Reliability

Latency

Cost

&#x20;     ↓

Role Selection

&#x20;     ↓

Fallback Strategy

&#x20;     ↓

Human Approval

```



This keeps Arc's AI development environment flexible while allowing model choices to evolve with evidence, availability, cost, and project requirements.
