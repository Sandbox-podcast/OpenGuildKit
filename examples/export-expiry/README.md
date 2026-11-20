# Check an export link on a pull request

This example uses one opt-in catalog pack and Git. Keep the pack in a central policy repository at `packs/export-link-expiry.json`. Copy the [example pack](policy/packs/export-link-expiry.json) there, then commit it. Keep the [project profile](project.json) in the project's trusted configuration and select the `export-link-expiry` pack. The pull request's commit supplies only the export data.

Run these commands after your CI system has fetched the policy commit and the proposed code commit. `PROFILE` is the trusted project directory, `POLICY` is the local policy repository and `TARGET` is the local target repository.

```bash
openguildkit --project "$PROFILE" --policy-repo "$POLICY" --policy-commit "$POLICY_SHA" init --answers project.json
openguildkit --project "$PROFILE" --policy-repo "$POLICY" --policy-commit "$POLICY_SHA" sync
openguildkit --project "$PROFILE" --policy-repo "$POLICY" --policy-commit "$POLICY_SHA" ci-check --target-repo "$TARGET" --commit "$HEAD_SHA"
```

Use `init` only when creating a profile. With an existing profile, add the pack ID to `.openguildkit/project.json` and run `sync`. Supply the same policy options to `check` or to a task command that reads the profile. `check` continues to verify the generated instructions.

`ci-check` reads `downloadLinkMinutes` from `export.json` in the exact target commit. It generates JSON with the instruction, the profile fingerprint, the rule version, both Git SHAs and the verdict. Exit code 0 means success, 1 means the value failed the rule, and 2 means evaluation could not run. Run the command identically in GitHub Actions or Jenkins, and configure the CI system to retain the JSON report on a failing check. Run the CLI and load the profile from trusted revisions when evaluating an unreviewed pull request.

To replay the update, evaluate two commits with 45 and 30 minutes at the original 60-minute policy SHA. Publish a new policy commit with `max_minutes: 30` and a new pack version. Reuse the same target SHAs and replace only `POLICY_SHA`. Both commits pass at 60 minutes. The 45-minute commit fails at 30 minutes and the 30-minute commit still passes.

The [end-to-end test](../../tests/e2e/test_export_ci.py) runs both phases, checks that the instructions and verdict have the same rule source, and replays the previous policy. Your CI system supplies the trigger and the list of open pull requests.

The [CI coordinator](../../integrations/ci/README.md) can watch open pull requests and schedule these rechecks. It uses the same export pack through the supplied [catalog index](policy/policy/catalog.json).
