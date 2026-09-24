# Expected Answers — RAG Verification Set

*Synthetic demo data. Use this to verify Ask Arc objectively.*

An answer is correct only if it states the fact **and** cites the
document named here. An answer that states the fact without a citation,
or cites a different document, is a retrieval failure even when the text
happens to be right.

| # | Question | Expected answer | Must cite |
|---|---|---|---|
| 1 | How many days of annual leave do I get? | 26 days, plus UK public holidays | Leave Policy |
| 2 | How many leave days can I carry over? | 5 days, and they must be used by 30 June | Leave Policy |
| 3 | How long is the minimum password? | 14 characters | IT and Security Policy |
| 4 | Does Acme make me rotate my password? | No — only on suspicion of compromise | IT and Security Policy |
| 5 | How quickly must I report a lost laptop? | Immediately, and within 2 hours of discovery | IT and Security Policy |
| 6 | What is the pension match? | Up to 8% of salary | Benefits |
| 7 | How much learning budget do I have? | £1,500 per year and 5 paid days | Benefits |
| 8 | How many days a month must I be in the office? | At least 8 | Benefits |
| 9 | How long is probation? | 3 months | Joining Acme |
| 10 | When must I complete security induction? | Within the first 5 working days | Joining Acme |
| 11 | How many people work at Acme? | 248 | Company Overview or Departments |
| 12 | When does the financial year start? | 1 April | Company Overview |
| 13 | Who runs Security Operations? | Tom Whitfield | Company Overview or Departments |
| 14 | What does Managed Workplace Standard cost? | £42 per seat per month | Service Catalogue |
| 15 | What is the minimum seat commitment? | 25 seats, 12 months | Service Catalogue |
| 16 | What service credit applies to a missed target? | 5% per missed target, capped at 25% a month | Service Catalogue |
| 17 | How much parental leave does a non-birthing parent get? | 8 weeks at full pay, from day one | Leave Policy |
| 18 | What is the backup retention default? | 30 days | Service Catalogue |

## Negative cases

These must **not** produce a confident company answer. Arc should say
the company knowledge does not cover it.

| # | Question | Correct behaviour |
|---|---|---|
| N1 | What is Acme's share price? | Not in company knowledge — Acme is private and no document states this |
| N2 | How many days of leave do contractors get? | Not in company knowledge — the policy covers permanent employees only |
| N3 | What is the capital of France? | Unrelated to company knowledge; answer generally if at all, clearly separated from company knowledge |
| N4 | What were Q3 sales in Portugal? | Not in company knowledge — no document contains this |

## Cross-tenant case

| # | Attempt | Correct behaviour |
|---|---|---|
| X1 | Ask these questions signed in to a different tenant | No answer and no citations — these documents belong to `ref-acme-technologies` |

## Observed retrieval, 23 September 2026

Measured against a running instance with `EMBEDDING_PROVIDER=deterministic`,
asking as `ref-acme-technologies-employee-1`. "Rank" is the position of
the document that actually contains the answer.

| Question | Correct document rank |
|---|---|
| Annual leave days | 1 |
| Minimum password length | 1 |
| Pension match | 1 |
| Probation length | 1 |
| Service credit for a missed target | 1 |
| Managed Workplace Standard price | **3** |

The pricing question is the honest weak spot: Company Overview and
Departments outrank the Service Catalogue, because both mention service
lines by name while the price sits in a table.

This is expected with the deterministic embedding provider, which
produces non-semantic vectors — ranking is effectively lexical, so a
question whose wording overlaps the wrong document retrieves the wrong
document. It is a fair baseline for demonstrating that retrieval and
citation work end to end; it is **not** a measurement of Arc's retrieval
quality with a real embedding model. Re-run this table after configuring
a production embedding provider before drawing any conclusion about
ranking.
