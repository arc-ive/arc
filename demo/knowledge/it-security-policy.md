# Acme Technologies — IT and Security Policy

*Synthetic demo document. Version 5.0, effective 1 February 2026.*

## Passwords and authentication

Passwords must be at least **14 characters**. Acme does not enforce
periodic rotation; passwords are changed only on suspicion of
compromise, in line with NCSC guidance.

**Multi-factor authentication is mandatory** for all staff on email,
the VPN, the cloud consoles and the client management platform.
Hardware security keys are issued to everyone in Security Operations
and to all staff with production access.

Password reuse across Acme and personal accounts is prohibited. The
company password manager is **1Vault**, licensed for every employee
including personal-family use.

## Devices

Company laptops are **fully disk encrypted** and enrolled in endpoint
management before issue. Personal devices may access email and chat but
**never** client data or production systems.

A lost or stolen device must be reported to the Service Desk
**immediately, and in any case within 2 hours** of discovery.

## Data classification

| Class | Meaning | Handling |
|---|---|---|
| Public | Published material | No restriction |
| Internal | Default for company information | Acme staff only |
| Confidential | Client data, contracts, personal data | Named-access only, encrypted at rest |
| Restricted | Credentials, security findings, legal matters | Security team approval per access |

Client data is **Confidential by default**.

## Incident reporting

Suspected security incidents go to **security@acme.example** or the
`#security-incidents` channel. Acme's target is to **acknowledge within
30 minutes** and to have an incident lead assigned **within 1 hour**.

Staff who report an incident in good faith are never penalised, including
when the incident was caused by their own mistake.

## Access reviews

Access to Confidential and Restricted systems is reviewed **quarterly**
by the system owner. Leavers are deprovisioned on their **final working
day**, before 17:00.
