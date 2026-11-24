# Run and measure the pilot in observation mode

Use the same two team repositories for the policy recheck and the comparison
with a reusable GitHub Actions workflow. The [local rehearsal](pilot-rehearsal-2026-11-23.md)
records what was exercised before the team pilot.

## Set up the observation pilot

1. Ask each repository owner to approve the repository, pilot window, central
   policy, local profile and evidence readers. Record the approved profile
   commit for each repository and who can stop the pilot.
2. After publication, download the wheel, Node archive and checksum manifest
   together. Verify both packages before installing. Set the same policy
   path in the two profiles. Use observation mode with the pinned
   [coordinator setup](../../integrations/ci/README.md#recheck-one-or-more-repositories).
3. Record the installation start and the first result verified in both
   GitHub Actions and Jenkins. Retain the run IDs, observation verdict,
   package version, PR commit, profile commit and policy commit. Use a
   read-only proof when collecting these timings outside the team.
4. Use one approved candidate with a 45-minute export and another with a
   30-minute export. Under the original 60-minute policy both conform.
   Change the approved central rule to 30 minutes, leaving both PR commits
   and profiles fixed. Verify that only the 45-minute case deviates and
   that both runners bind the new verdicts to the new policy commit.
5. Record setup problems, verdict disagreements and operator interventions.
   Summarize which findings must be resolved before a blocking rollout and
   take that summary back to the owners.

[#259](https://github.com/Sandbox-podcast/OpenGuildKit/issues/259) still needs the
two owners' agreement and the public package validation
([#254](https://github.com/Sandbox-podcast/OpenGuildKit/issues/254) and
[#255](https://github.com/Sandbox-podcast/OpenGuildKit/issues/255)).

## Verify recovery against the active references

Run this exercise on the authorized pilot fixture with a persistent state
directory. Record each observation with UTC time, attempt identifier, Actions
run ID, PR SHA, profile SHA, policy SHA and verdict.

| Step | Observation to collect |
| --- | --- |
| Start a batch and stop the coordinator after GitHub accepts a dispatch | Preserve the accepted run ID and the coordinator state at the interruption. |
| Restart against the same state directory and refs | The existing run is recovered by its attempt, and the same work is dispatched once. |
| While another run is in progress, advance the approved policy | The PR SHA stays fixed. The proof with the previous policy stays historical. Only the proof with the active refs can satisfy the current check. |

The automated [watcher test](../../integrations/ci/test/watch.test.mjs) stops
a real local process during dispatch with a simulated provider. The hosted
counterpart remains part of [#261](https://github.com/Sandbox-podcast/OpenGuildKit/issues/261).

## Compare against a shared GitHub workflow

Use [shared-workflow.yml](shared-workflow.yml) as the comparison arm. Copy it
to the team's trusted `.github/workflows` directory and call it with
`workflow_call`. Pin the comparison script, policy and target to the approved
commits. The referenced policy repository must be readable from the caller.
The workflow reads committed export data and produces both an `AGENTS.md`
instruction and a structured verdict from the same central rule. Collect
the artifact for the reviewer and the agent for that run. See
[reusable workflow setup](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

For [#260](https://github.com/Sandbox-podcast/OpenGuildKit/issues/260), pair each
representative request with an identical PR commit, policy update and review
goal in both arms. Use the same runner type and cache condition. Alternate the
order between teams. The initial protocol uses three paired repetitions per
case to check repeatability. Report the actual sample sizes, medians and
ranges.

| Measure | Record for each arm |
| --- | --- |
| First verified PR | Start of installation, first result visible and elapsed time. |
| Change of central rule | Time until the new verdict is visible for the unchanged SHA and the count of human interventions. |
| Review | Active reviewer minutes, separated from queue and runner time. |
| False positives | Deviations on cases the owners committed to treating as conforming before the comparison. Keep the denominator. |
| Execution cost | Runner time and actual cost if observable, with retries counted. |
| Board contributions | Human-confirmed decisions changed or clarified by a board and the evidence it contributed. |

Use anonymized identifiers and mark missing measures explicitly. The
comparison of local check outputs is a prerequisite. The measures of team
work, hosted execution and review are collected in the actual pilot.

## Rank the next extension

Use the requests seen in the pilot for
[#268](https://github.com/Sandbox-podcast/OpenGuildKit/issues/268). For each,
record the detected stack or sector, matched patterns and packs, missing
guidance, number of distinct PRs affected and highest observed impact
(blocked setup, missed check or manual workaround). Prioritize reproduced
blockers and break ties by frequency. Record the source and date of each
candidate rule. Keep technical practices distinct from legal obligations
that require review by a sector specialist.

Rust is a candidate if the pilot confirms demand. Start with a small Cargo
package and a workspace that inherits package settings. Verify detection
of the manifest, scope of workspace members, and distinction between the
Rust edition and minimum toolchain version. Test malformed manifests and
mixed Rust and non-Rust components. This is a proposed scope awaiting the
needs measured in [#259](https://github.com/Sandbox-podcast/OpenGuildKit/issues/259)
and [#260](https://github.com/Sandbox-podcast/OpenGuildKit/issues/260).
The Cargo references were checked on 23 November 2026.
[Manifest format](https://doc.rust-lang.org/cargo/reference/manifest.html)
and [Rust version](https://doc.rust-lang.org/cargo/reference/rust-version.html).
