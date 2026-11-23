# Local pilot rehearsal, 23 November 2026

Run on Windows with Python 3.12.7 and Node 22.20.0. The wheel and the Node
archive were built from OpenGuildKit commit
[`6ec06a5`](https://github.com/Sandbox-podcast/OpenGuildKit/tree/6ec06a59c240c34e2ccdd4b670da9b071d669971),
installed into fresh environments and verified against their local SHA-256
manifest. Both reported `0.17.0`. The rehearsal used temporary Git
repositories and synthetic data. The public release and the team repositories
remain prerequisites for the [observation pilot](pilot.md).

## Shared rule on unchanged commits

The Python check from the wheel, the Node coordinator in observation mode and
the shared workflow's script agreed on all four evaluations. The shared script
produced the agent instruction for each policy commit.

| Export from unchanged target commit | Original limit, 60 min | Updated limit, 30 min |
| --- | --- | --- |
| 45 min | Conforms | Deviates |
| 30 min | Conforms | Conforms |

Recorded identifiers from the temporary repositories:

- Target commits: `495c0d8c15d35926c36bd9c69783f1c84d88b794` (45 minutes)
  and `7d9e9155a2add114c1b46857da2863792e78112d` (30 minutes).
- Central policy: `594ab3a4331bacde09bfca9712f46df5f4115ae6` (60 minutes)
  and `f0e610baddd023a4ac9a6daeb65cd6f9a2dad690` (30 minutes).
- Node profile commit in both repositories: `764f5d42076d9899916a1b36e6c6c2124d7317f1`.
  The Python profile and policy fingerprint changed with the policy,
  from `a2ce9ec2eb4c6430c1de48b3c8703b51908ce3a57f6e7fae787bdd9137f25878`
  to `83392576c901f08823bc71b6a345e40da4ceda78d5081a44c2f828eb54e44619`.

The local process times, one sample for each evaluation with startup, ranged
from 397 to 430 ms for the Python check, 296 to 352 ms for the Node coordinator,
and 235 to 282 ms for the reference script. Hosted timing, GitHub Actions
and Jenkins parity on the two pilot repositories, operator work and review
time remain to be measured.

## Restart after a dispatch

The [new watcher exercise](../../integrations/ci/test/watch.test.mjs) was run
against the installed Node archive with a simulated GitHub provider.

| Event | Result |
| --- | --- |
| Provider accepted run 42 | The child process exited while the local attempt was still requesting. The run ID was saved only in the simulated provider. |
| Watch started again | It recovered run 42 by attempt `9bbde5b7-8298-4a27-9ec1-b595dbc01167`, verified the proof and issued no duplicate dispatch. |
| Policy changed, PR SHA stayed fixed | Run 43 was dispatched. A proof bearing the old policy was marked as a mismatch. |

These are local process and state observations. The same sequence with an
accepted run on GitHub remains part of the hosted recipe.

## Field kit

The installed wheel ran the scripted parts of all three scenarios with three
isolated folders each, using the existing mock tools.

| Scenario | Compared keys | Result |
| --- | --- | --- |
| S1 | 13 | Identical in all three folders |
| S2 | 14 | Identical in all three folders |
| S3 | 14 | Identical in all three folders |

The [0.16.1 campaign](../field-tests/reports/2026-11-21.md) compared the same
counts. Its S3 consultation differed when one team changed the alert import
order. The 0.17.0 rehearsal uses the scripted order, so it confirms
repeatability under that order. The two tests of a revised brief passed on
the installed wheel and preserved the earlier round. The collector returned
exit code 1 and named all 30 missing reports, and the command wrapper recorded
the installed CLI version in a tester transcript. The full campaign still
requires 30 tester runs, reports and review of their findings. Differences in
questions, completion and blockers remain to be measured.

## Catalog inventory

Ran `detect --json` from the candidate wheel on separate minimal projects.
Pack, pattern and sector coverage was read from the candidate's source commit.

| Manifest | Detected in the sample | Catalog coverage to build on |
| --- | --- | --- |
| `build.gradle.kts` with the Kotlin JVM plugin | Kotlin 2.2.0 | The Android pattern includes Kotlin. Evaluate non-Android Kotlin requests separately. |
| `Cargo.toml` with a standalone package | No component returned | Cargo detection is the first gap to verify if Rust appears in the team pilot. |
| `composer.json` with `php: ^8.3` | PHP ^8.3 | Language detected. No dedicated PHP pattern was found. |
| `Gemfile` with a Ruby declaration | Ruby 3.4.2 | Language detected. No dedicated Ruby pattern was found. |

The catalog lists eight specialized sectors plus the general profile. It
includes critical infrastructure and software publishers, alongside
education, healthcare, insurance, financial services, e-commerce and the
public sector. Automotive and aerospace remain roadmap items. The sample
builds a starting inventory. Pilot frequency and observed impact will
determine which extension is chosen.
