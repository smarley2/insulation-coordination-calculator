# Security Policy

## Supported versions

Security fixes are provided for the latest published release only. Users should upgrade to the newest release before reporting a problem that may already have been corrected.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting feature:

1. Open the repository's **Security** tab.
2. Select **Advisories**.
3. Select **Report a vulnerability**.
4. Include the affected version, operating system, reproduction steps, expected impact, and any proposed mitigation.

You should receive an initial acknowledgement within seven days. Validation, remediation, and disclosure timing depend on the severity and complexity of the report. Please allow time for a fix and coordinated disclosure before publishing details.

## Sensitive and licensed material

Do not attach or publish:

- licensed IEC standard PDFs or extracted standard content;
- private `.icrules` or `.icproj` files;
- audit exports containing licensed, customer, or project data;
- credentials, tokens, personal data, or proprietary engineering information.

Create a minimal synthetic reproduction whenever possible. If sensitive material is essential to demonstrate the issue, describe it in the private report and wait for instructions before sharing it.

## Scope

Security reports may include, but are not limited to:

- unsafe processing of PDFs, project files, or rule packages;
- path traversal, arbitrary file access, or unintended file modification;
- code execution or command injection;
- dependency or packaged-runtime vulnerabilities;
- exposure of licensed, private, or user-provided information;
- release integrity or supply-chain weaknesses.

Engineering disagreements, calculation requests, and ordinary defects should use the public bug-report template instead.