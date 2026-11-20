# Coordinate checks on open pull requests

The CI coordinator is an optional Node.js integration for OpenGuildKit. It reconciles open pull requests against active rule and profile revisions, runs the checks in Jenkins and GitHub Actions, and keeps historical reports separate from the verdict applicable to the current commit. The Python CLI handles project instructions and specialist reviews.

## Install

From the root of a trusted checkout, with Node.js 22+, npm and Git:

```bash
npm pack ./integrations/ci
npm install --global ./openguildkit-0.16.0.tgz
openguildkit-ci --help
```

The coordinator installs `openguildkit-ci` and `openguildkit-ci-agent`. GitHub operations also use GitHub CLI with access to the selected repositories. The coordinator state directory must support hard links. Put it on persistent storage and restrict access to the operators of the integration.

## Share the policy

Copy the [example policy repository files](../../examples/export-expiry/policy/) into a central Git repository. Both the Python project and the CI coordinator read `packs/export-link-expiry.json`. The CI catalog index provides ownership and selects the file. The approved CI profile, at `openguildkit.json` on a trusted target branch, selects the same path. The two project profiles serve different workflows and can be reviewed independently.

```json
{
  "schemaVersion": 1,
  "owner": "@platform",
  "ruleId": "export-link-expiry",
  "policyPath": "packs/export-link-expiry.json",
  "targetPath": "export.json"
}
```

Start in observation mode. Use `openguildkit-ci onboard` to create a profile proposal, and `openguildkit-ci github-approve-profile` to verify the maintainer's approval. Older numeric-version policy files and existing coordinator profiles remain supported.

## Recheck one or more repositories

Provide the organization and repository IDs, corresponding local Git checkouts, approved branch references and the GitHub workflow that can run a recheck. The paths in the configuration are relative to the configuration file.

```json
{
  "policyRepo": {
    "id": "example/policies",
    "path": "./policies",
    "ref": "refs/heads/main"
  },
  "projects": [
    {
      "id": "example/portal",
      "path": "./portal",
      "profileRef": "refs/heads/main",
      "workflow": {
        "file": "openguildkit.yml",
        "ref": "pilot/recheck-base",
        "evidenceBranch": "openguildkit-evidence"
      }
    }
  ]
}
```

Use `openguildkit-ci github --config integration.json --state ./state --run` to inspect the resulting checks. For continuous operation, copy the [GitHub Actions recheck template](pilot/recheck-workflow.yml) to `.github/workflows/openguildkit.yml` on a trusted workflow branch. Set `pilot/recheck.json` with `policyRepository` and `policyRef`, and put the archive's SHA-256 followed by its filename in `pilot/recheck-kit.sha256`. Host the pinned archive as a GitHub Release asset of that project, as expected by the template. Provision read-only policy access if the policy repository is private.

Schedule `openguildkit-ci watch --config integration.json --state ./state` on a trusted Jenkins agent with a persistent state directory and concurrent builds disabled. The [Jenkins launcher](pilot/run-watch-jenkins.mjs) supports installing the CLI from a verified archive before running the scheduled check. Add `--publish` when the Jenkins identity has permission to write to the configured evidence branch and publish statuses. Set up that branch in each project.

A run that executes new checks refreshes the active references afterward. If they changed during evaluation, the report still links to the evidence just produced in `executedEvidence`. The `current` entries track the newly active references.

The workflow templates retain their pilot branch names and configuration filenames. Adjust them for the deployment. Keep checkout, validation and report publication on trusted revisions. The project keeps its normal merge review and approval settings.

## Required checks and waivers

`openguildkit-ci gate` derives the merge condition from the current PR, profile and policy. `openguildkit-ci merge` can recheck a time-limited waiver immediately before submitting the exact PR SHA to GitHub. Use the [required check](pilot/required-workflow.yml) and [protected merge](pilot/broker-workflow.yml) templates to adapt branch enforcement to a pilot. Their GitHub App and credentials are provisioned separately by the repository owner.

See `openguildkit-ci --help` for the profile, agent brief, release discovery, recheck and merge subcommands. The [tests](test/) exercise rule updates, stale evidence, recovery and scoped merge decisions.
