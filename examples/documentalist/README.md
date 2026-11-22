# Example: documentation export

`docs-site/` is the output of `openguildkit docs export` for the fictional [request status task](../request-status/) once completed. See [Project documentation and sharing](../../docs/documentation.md) for the import into Documentalist.

| File | Used by |
|---|---|
| `profile.json` | `init --answers`: the request status profile with one check command, `git --version`, since the example has no code to test |
| `answers.json` | `task consult --answers`: the request status answers plus `affected` and `outcome`, which the Learn and Reference pages quote |
| `result.json` | `task result --file`: the pull request and the two acceptance criteria met |
| `replay.py` | Runs the whole flow and compares the export with `docs-site/` |

## Replay

From the repository root, with an empty folder:

```bash
python examples/documentalist/replay.py --project /tmp/docs-example
```

The first run sets up the project, opens the task with the brief of `examples/request-status/`, consults the boards and records `examples/request-status/review.json`. Approval needs a person: in a terminal the script asks your name and lets you approve; otherwise it prints the `task decide` command to run yourself. Run the script again with the same `--project`: it runs `task verify`, records `result.json` (each pack rule is reported not applicable by the approver, because the example changes no code), completes the task, exports `docs-site/` and lists any file that differs from this folder.

The blog page is named and dated after the day the task is completed. The script sets `SOURCE_DATE_EPOCH` to 2026-11-20 (see [reproducible dates](../../docs/documentation.md#reproducible-dates); each command says so on stderr), so `diff -r PROJECT/docs-site examples/documentalist/docs-site` is empty on any day, which `tests/test_publishing.py` checks. It exports the task sections only (`--sections reference,learn,blog`): the project page quotes the catalog's rule packs, which change from one version to the next.
