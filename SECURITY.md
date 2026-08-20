# Security policy

LumenPlot is **pre-alpha**. The public API is unstable, production use is not
recommended, and security support is best-effort while the project is in this
stage.

## Supported versions

| Version line | Security support |
| --- | --- |
| `pre-alpha` development line | Best-effort review; no response-time or fix-time guarantee |
| Unannounced or absent release | Not supported |

A future release policy must replace this table before a stable release is
announced. No release or security guarantee is created by this document.

## Reporting a vulnerability

Please do **not** open a public issue, pull request, or discussion for a
vulnerability. Do not include secrets, exploit instructions, or sensitive
proof-of-concept material in public text.

The first reporting route to verify is GitHub's private vulnerability reporting
or security-advisory flow in the repository's **Security** tab. Use that
private flow when it is enabled and visible to you. The audit that produced this
baseline did not verify that the feature is enabled for the eventual public
repository.

If no private GitHub reporting route is visible, do not disclose vulnerability
details publicly. Publication remains blocked until maintainers configure and
verify a private GitHub-native route. This policy intentionally does not invent
an email address or promise a channel that has not been confirmed.

When the private route is available, include only the minimum useful
information: affected revision or component, impact, reproduction steps that do
not expose real secrets, and a suggested mitigation if known. There is no
published response-time or remediation-time commitment for pre-alpha software.

## Other sensitive reports

Sensitive conduct concerns follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
General usage and reproducible non-sensitive problems follow
[SUPPORT.md](SUPPORT.md). Do not use public issue forms for either a security
report or a sensitive conduct report.
