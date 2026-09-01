# Security policy

## Supported versions

| Version | Security fixes |
|---|---|
| 0.2.x | Yes |
| 0.1.x and earlier | No |

## Reporting a vulnerability

Do not open a public issue for a vulnerability or attach a real customer export anywhere
in this repository. Use [GitHub private vulnerability reporting](https://github.com/m7mdwb/martech-verify/security/advisories/new).

Include only the information needed to reproduce the problem safely:

- affected skill, command and version or commit;
- security impact and who could be affected;
- a minimal reproduction made from synthetic data;
- expected result, actual result and exit code;
- a suggested fix, if you have one.

Especially useful reports include unredacted personal data in any output format, a malformed
or untrustworthy export receiving a clean verdict, unsafe file handling, or an agent
workflow crossing its stated read-only boundary.

We aim to acknowledge a report within five business days and provide an initial assessment
within ten. Please allow time for a fix and release before public disclosure. Reports about
Codex, Claude Code, GitHub, Python, or another upstream platform should be sent to that
project unless the vulnerability is caused by this repository's code or instructions.

## Handling sensitive test cases

Never submit production URLs, leads, credentials, tokens, customer identifiers or other
personal data. Replace them with synthetic values that preserve the structure of the bug.
The fixtures in this repository are intentionally fictional and are the preferred pattern
for a reproducible report.
