"""Field campaign kit: thirty testers adopt OpenGuildKit as real teams would.

    python examples/field-tests/field.py list
    python examples/field-tests/field.py prepare --out DIR
    python examples/field-tests/field.py brief TESTER --out DIR
    python examples/field-tests/field.py cohorts --out DIR [--teams N]
    python examples/field-tests/field.py collect --out DIR [--open-issues]

`prepare` creates one folder per tester and the shared repository of the three teammates.
`brief` prints what one tester is asked to do: give it to an autonomous agent. `cohorts`
plays the scripted part of each scenario in several folders without any agent and compares
the results. `collect` checks that every tester reported, merges the findings and compares
the teams that played the same scenario; with --open-issues it files each issue draft with gh. No network, no account, no key: company tools are
mocks, and every name in the campaign is invented.
"""

import argparse
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import fingerprint as fingerprint_script  # noqa: E402  (the kit's own module, next to this file)
from field_cli import INSTALLED_ENV, uses_installed_package  # noqa: E402
from fingerprint import fingerprint  # noqa: E402

SEVERITIES = ("blocker", "major", "minor", "suggestion")
KINDS = ("bug", "confusing", "missing", "docs")
OUTCOMES = ("completed", "partial", "blocked")
FINDING_KEYS = ("title", "severity", "kind", "command", "observed", "expected")
PERSONA_KEYS = ("id", "who", "language", "project", "answers", "task", "focus")
GIT_PERSON = ("-c", "user.name=Team lead", "-c", "user.email=lead@example.test")
# A tester's transcript must reach the handoff of an approved task, or a step after it.
REACHED = ("handoff", "verify", "result", "complete")


def load_campaign() -> dict:
    return json.loads((HERE / "campaign.json").read_text(encoding="utf-8"))


def testers(campaign: dict) -> list[dict]:
    """Every tester of the campaign with its group: a persona, a scenario team or a teammate."""
    rows = [{"id": persona["id"], "group": "persona", "spec": persona} for persona in campaign["personas"]]
    for scenario in campaign["scenarios"]:
        rows += [{"id": f"{scenario['id']}-team{number}", "group": "scenario", "spec": scenario}
                 for number in range(1, scenario["teams"] + 1)]
    rows += [{"id": mate["id"], "group": "teammate", "spec": mate} for mate in campaign["teammates"]]
    return rows


def campaign_problems(campaign: dict) -> list[str]:
    """What is wrong with the campaign file, so that a campaign never starts on a broken one."""
    problems = []
    ids = [tester["id"] for tester in testers(campaign)]
    problems += [f"Tester ID used twice: {name}" for name in sorted({name for name in ids if ids.count(name) > 1})]
    for persona in campaign["personas"]:
        missing = [key for key in PERSONA_KEYS if not str(persona.get(key, "")).strip()]
        if missing:
            problems.append(f"Persona {persona.get('id', '?')} lacks: {', '.join(missing)}")
    for scenario in campaign["scenarios"]:
        folder = HERE / "scenarios" / scenario["id"]
        for name in ("init-answers.json", "task.json", "project"):
            if not (folder / name).exists():
                problems.append(f"Scenario {scenario['id']} lacks {name}")
        if scenario["teams"] < 2:
            problems.append(f"Scenario {scenario['id']} needs at least two teams to compare")
    return problems


def cli(project: Path, *arguments, check: bool = True) -> subprocess.CompletedProcess:
    arguments = [str(argument) for argument in arguments]
    result = subprocess.CompletedProcess(arguments, *fingerprint_script.run(project, *arguments))
    if check and result.returncode:
        raise ValueError(f"openguildkit {' '.join(map(str, arguments))} failed in {project.as_posix()}: "
                         f"{result.stderr.strip() or result.stdout.strip()}")
    return result


def git(folder: Path, *arguments) -> str:
    result = subprocess.run(["git", *arguments], cwd=folder, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"git {' '.join(arguments)} failed in {folder.as_posix()}: {result.stderr.strip()}")
    return result.stdout.strip()


def _commit_all(folder: Path, message: str) -> None:
    git(folder, "add", "-A")
    git(folder, *GIT_PERSON, "commit", "-q", "-m", message)


def _wrapper(path: Path, script: str, *arguments: Path) -> None:
    """Keep the selected package and interpreter when a tester runs the command later."""
    invocation = shlex.join([sys.executable, str(HERE / script), *map(str, arguments)])
    installed = int(uses_installed_package())
    path.write_text(f'#!/bin/sh\n{INSTALLED_ENV}={installed} exec {invocation} "$@"\n', encoding="utf-8")
    path.chmod(0o755)


@contextlib.contextmanager
def _launcher_on_path(out: Path):
    """Put the campaign's openguildkit command first on the PATH while the kit sets projects up.

    host apply fails while the hooks of the host cannot find openguildkit, and a source checkout does not install it.
    The testers get the same command on their PATH, so the kit's projects match theirs."""
    folder = out / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        _wrapper(folder / "openguildkit", "logged.py", out / "runs")
    else:
        invocation = subprocess.list2cmdline([sys.executable, str(HERE / "logged.py"), str(out / "runs")])
        installed = int(uses_installed_package())
        (folder / "openguildkit.cmd").write_text(f"@set {INSTALLED_ENV}={installed}\r\n@{invocation} %*\r\n",
                                                 encoding="utf-8")
    before = os.environ.get("PATH")
    os.environ["PATH"] = os.pathsep.join(filter(None, [str(folder), before]))
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = before


def prepare(out: Path) -> dict:
    """Create every folder the briefs name, the commands on PATH and the teammates' shared repository."""
    if os.name != "posix":
        raise ValueError("A field campaign needs Linux or macOS: the person's stand-in types at a pseudo-terminal.")
    campaign = load_campaign()
    problems = campaign_problems(campaign)
    if problems:
        raise ValueError("The campaign file is not usable: " + "; ".join(problems))
    cli_version = cli(HERE, "--version").stdout.strip()
    out = out.resolve()
    for name in ("bin", "results", "shared"):
        (out / name).mkdir(parents=True, exist_ok=True)
    ids = [tester["id"] for tester in testers(campaign)]
    for name in ids:
        (out / "runs" / name).mkdir(parents=True, exist_ok=True)
    _wrapper(out / "bin" / "person-decide", "person_decide.py")
    _wrapper(out / "bin" / "person-act", "person_act.py")
    _wrapper(out / "bin" / "fingerprint", "fingerprint.py")
    remote = out / "shared" / "remote.git"
    with _launcher_on_path(out):
        if not remote.exists():
            seed = out / "shared" / "seed"
            shutil.copytree(HERE / "scenarios" / "s1" / "project", seed)
            git(seed, "init", "-q", "-b", "main")
            cli(seed, "init", "--answers", HERE / "scenarios" / "team-answers.json")
            cli(seed, "integrations", "--host", "claude-code")
            cli(seed, "host", "apply")
            _commit_all(seed, "Support portal with OpenGuildKit set up")
            git(out / "shared", "clone", "-q", "--bare", "seed", "remote.git")
    try:
        commit = git(REPO, "rev-parse", "HEAD")
    except (ValueError, OSError):
        commit = "unknown"
    record = {"commit": commit, "cli_version": cli_version, "python": sys.version.split()[0], "testers": ids}
    (out / "campaign.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _rules(out: Path) -> str:
    text = (HERE / "TESTERS.md").read_text(encoding="utf-8")
    return text.replace("{out}", out.as_posix()).replace("{repo}", REPO.as_posix())


def _persona_task(persona: dict, workspace: Path) -> str:
    return f"""You are {persona['who']}. Language: {persona['language']}.
Your workspace is {workspace.as_posix()}/ (your project goes in {workspace.as_posix()}/project).

1. Read the README and the pages a newcomer would read before starting.
2. Create the project: {persona['project']}. Make the files small but real, commit them.
3. Set OpenGuildKit up for this project as the documentation says: look at what it detects, read the questionnaire
   (init --questions), write the person's answers and run init with them, install the agent files for the host,
   apply and check the host settings, run check. How the person answers: {persona['answers']}
4. Connect the company's tools with mocks and query one of them.
5. First piece of work, through the whole flow to "done", with a real code change once approved: {persona['task']}.
6. Then: {persona['focus']}
7. Before you stop, try five things a curious or careless user would try on this project, of your own choosing,
   different from the above."""


def _scenario_task(scenario: dict, tester: str, workspace: Path, person: str) -> str:
    folder = (HERE / "scenarios" / scenario["id"]).as_posix()
    extra = scenario["extra"].replace("{repo}", REPO.as_posix()).replace("{kit}", HERE.as_posix())
    return f"""You are one of {scenario['teams']} teams that were given exactly the same scenario, each in its own folder, to see
whether the same inputs give the same results. Your workspace is {workspace.as_posix()}/ (your project goes in
{workspace.as_posix()}/project).

Part 1, scripted. Do exactly this, in this order, and nothing else in between:
a. Copy the contents of {folder}/project/ into your project folder, run git init there and commit.
b. Run: openguildkit init --answers {folder}/init-answers.json
c. Run: openguildkit integrations --host {scenario['host']} ; then openguildkit host apply
d. Run: openguildkit tools apply {' '.join(scenario['tools'])} --mock
e. Read {folder}/task.json. Write its "answers" object to answers.json in your workspace (outside the project). Run
   openguildkit task new with its "brief" and --id set to its "id", then openguildkit task consult ID --answers
   answers.json. {extra}
f. Run: fingerprint --project YOUR_PROJECT --task ID --answers YOUR_ANSWERS_FILE > {workspace.as_posix()}/fingerprint.json
If a scripted step fails, stop Part 1 there and report the failure as a finding.

Part 2, free. Continue the task as the coding agent of a team would: review each board with evidence from the
project and the mocks, record the review, run the deliberation if boards disagree, have the person decide with
person-decide (the person is "{person}", who approves if no board blocks and asks for changes otherwise), implement
the change for real, record the results and complete the task. Then try three things of your own choosing on this
project. ({tester} is your name in the campaign.)"""


def _teammate_task(mate: dict, workspace: Path, remote: Path) -> str:
    return f"""You are {mate['name']}, one of three developers of the same team who work at the same time on the same repository,
each on their own machine. The team's repository is the bare git repository {remote.as_posix()} (branch main). It
already has OpenGuildKit set up and committed. Your two teammates are doing their own work right now and will push
to the same branch.

Your workspace is {workspace.as_posix()}/. Clone the repository into {workspace.as_posix()}/project and work there.
Commit as "{mate['name']}" with an example.test address.

Your work: {mate['work']}. Take it through the whole OpenGuildKit flow as the coding agent (scoping answers from the
brief, board passes with real evidence, review, the person's decision with person-decide where the person is
"{mate['name']}", implementation, results, completion), export the decision record, commit the code and the files
OpenGuildKit says belong in git, and push to main. If the push is refused because main moved, pull with rebase,
resolve what must be resolved, and push again.

{mate['extra']}

What we want to learn from you three: which OpenGuildKit files conflict or change under a teammate, what a developer
sees after pulling a teammate's change to the project's rules (run check, task list and guard --json after each
pull), whether tasks kept on one machine make sense to the others, and anything that would make three people step on
each other. Do not coordinate outside git."""


def brief(tester_id: str, out: Path) -> str:
    """The whole text one tester receives: the common rules, then its own scenario."""
    campaign = load_campaign()
    tester = next((row for row in testers(campaign) if row["id"] == tester_id), None)
    if tester is None:
        raise ValueError(f"Unknown tester: {tester_id}. Run field.py list.")
    out = out.resolve()
    workspace = out / "runs" / tester_id
    if tester["group"] == "persona":
        task = _persona_task(tester["spec"], workspace)
    elif tester["group"] == "scenario":
        task = _scenario_task(tester["spec"], tester_id, workspace, campaign["person"])
    else:
        task = _teammate_task(tester["spec"], workspace, out / "shared" / "remote.git")
    return f"{_rules(out)}\n---\n\n# Your scenario\n\n{task}\n"


def play_scenario(scenario: dict, project: Path) -> dict:
    """The scripted part of a scenario, as a team is asked to play it; returns the fingerprint."""
    folder = HERE / "scenarios" / scenario["id"]
    shutil.copytree(folder / "project", project)
    git(project, "init", "-q", "-b", "main")
    _commit_all(project, "Scenario project")
    cli(project, "init", "--answers", folder / "init-answers.json")
    cli(project, "integrations", "--host", scenario["host"])
    cli(project, "host", "apply")
    cli(project, "tools", "apply", *scenario["tools"], "--mock")
    task = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    answers = project.parent / "answers.json"
    answers.write_text(json.dumps(task["answers"]), encoding="utf-8")
    cli(project, "task", "new", task["brief"], "--id", task["id"])
    consult = ["task", "consult", task["id"], "--answers", answers]
    if scenario["id"] == "s2":
        market = project / ".openguildkit" / "market"
        market.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", market / "support-portals.json")
        consult += ["--market", "support-portals"]
    cli(project, *consult)
    if scenario["id"] == "s3":
        cli(project, "task", "alerts", task["id"], "--import", folder / "npm-audit.json")
    return fingerprint(project, task["id"], answers)


def differing_keys(prints: dict[str, dict]) -> dict[str, dict[str, str]]:
    """For each key that is not the same for every team: what each team has, as text."""
    keys = sorted({key for data in prints.values() for key in data})
    differing = {}
    for key in keys:
        values = {team: json.dumps(data.get(key), sort_keys=True, ensure_ascii=False) for team, data in prints.items()}
        if len(set(values.values())) > 1:
            differing[key] = values
    return differing


def cohorts(out: Path, teams: int = 3) -> dict:
    """Play each scenario's scripted part in several folders, with no agent, and compare the fingerprints."""
    out = out.resolve()
    result = {}
    with _launcher_on_path(out):
        for scenario in load_campaign()["scenarios"]:
            prints = {}
            for number in range(1, teams + 1):
                folder = out / "cohorts" / f"{scenario['id']}-team{number}"
                if folder.exists():
                    shutil.rmtree(folder)
                folder.mkdir(parents=True)
                prints[f"team{number}"] = play_scenario(scenario, folder / "project")
            result[scenario["id"]] = {"keys": len(prints["team1"]), "differing": differing_keys(prints)}
    return result


def _findings(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, "no findings.json"
    except ValueError as error:
        return None, f"findings.json is not valid JSON ({error})"
    if not isinstance(data, dict) or data.get("outcome") not in OUTCOMES or not isinstance(data.get("findings"), list):
        return None, f"findings.json needs an outcome ({', '.join(OUTCOMES)}) and a findings list"
    for position, finding in enumerate(data["findings"], start=1):
        if not isinstance(finding, dict) or any(not str(finding.get(key, "")).strip() for key in FINDING_KEYS):
            return None, f"finding {position} needs {', '.join(FINDING_KEYS)}"
        if finding["severity"] not in SEVERITIES or finding["kind"] not in KINDS:
            return None, f"finding {position} has an unknown severity or kind"
    return data, None


def transcript(path: Path) -> tuple[str, str | None]:
    """How far a tester's commands.log goes: missing, before handoff, or handoff or later; and its last command."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "missing", None
    commands = [line[2:].rsplit("  (in ", 1)[0] for line in text.splitlines() if line.startswith("$ openguildkit")]
    for command in commands:
        try:
            words = shlex.split(command)
        except ValueError:
            continue
        if "task" in words and any(word in REACHED for word in words[words.index("task") + 1:words.index("task") + 2]):
            return "handoff or later", commands[-1]
    return "before handoff", commands[-1] if commands else None


def _draft_parts(draft: Path) -> tuple[str, list[str], str]:
    """The title, the labels and the body of an issue draft written by collect."""
    head, body = draft.read_text(encoding="utf-8").split("---\n", 1)
    fields = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
    return fields["title"], [label for label in fields.get("labels", "").split(",") if label], body


def open_issue(scenario: str, draft: Path) -> tuple[str | None, str | None]:
    """File one issue draft with gh in this checkout's repository: its address, or why it failed."""
    title, labels, body = _draft_parts(draft)
    body_file = draft.with_suffix(".body.md")
    body_file.write_text(body, encoding="utf-8")
    command = ["gh", "issue", "create", "--title", title, "--body-file", str(body_file)]
    for label in labels:
        command += ["--label", label]
    try:
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    except OSError as error:
        return None, f"{scenario}: gh issue create failed: {error}"
    if result.returncode:
        return None, f"{scenario}: gh issue create failed: {(result.stderr or result.stdout).strip()}"
    return result.stdout.strip(), None


def _divergence_draft(scenario: str, differing: dict) -> str:
    lines = [f"title: Scenario {scenario}: teams with the same inputs got different results", "labels: bug,field-test", "---",
             "## What differs", "",
             "The scripted part of a scenario is deterministic: the same files and the same commands must give the same",
             "fingerprint, so the threshold is zero: any key that differs is a defect. These keys differ between teams:",
             ""]
    for key, values in differing.items():
        lines.append(f"- `{key}`: " + "; ".join(f"{team} = {value[:120]}" for team, value in sorted(values.items())))
    lines += ["", "## Acceptance criteria", "",
              f"- `field.py cohorts` reports no differing key for scenario {scenario}.",
              "- A test reproduces the difference and fails without the fix."]
    return "\n".join(lines) + "\n"


def collect(out: Path, open_issues: bool = False) -> tuple[dict, list[str]]:
    """Check every tester's files and transcript, merge the findings and compare the teams of each scenario.

    With open_issues, each issue draft is filed with gh in this checkout's repository; never otherwise.
    """
    out = out.resolve()
    campaign = load_campaign()
    results = out / "results"
    results.mkdir(parents=True, exist_ok=True)
    problems, rows, merged, prints, issues = [], [], [], {}, []
    for tester in testers(campaign):
        workspace = out / "runs" / tester["id"]
        report = workspace / "REPORT.md"
        has_report = report.is_file() and report.stat().st_size > 0
        if not has_report:
            problems.append(f"{tester['id']}: no REPORT.md")
        data, problem = _findings(workspace / "findings.json")
        if problem:
            problems.append(f"{tester['id']}: {problem}")
        counts = {severity: 0 for severity in SEVERITIES}
        for position, finding in enumerate((data or {}).get("findings", []), start=1):
            counts[finding["severity"]] += 1
            merged.append({"ref": f"{tester['id']}#{position}", **finding})
        reach, last = transcript(workspace / "commands.log")
        if reach == "missing":
            problems.append(f"{tester['id']}: no commands.log, the transcript of its openguildkit commands")
        elif reach == "before handoff":
            problems.append(f"{tester['id']}: commands.log stops before task handoff (last: {last or 'no command'})")
        rows.append({"id": tester["id"], "group": tester["group"], "report": has_report,
                     "outcome": (data or {}).get("outcome", "not reported"), "log": reach, **counts})
        if tester["group"] == "scenario":
            try:
                prints.setdefault(tester["spec"]["id"], {})[tester["id"]] = json.loads(
                    (workspace / "fingerprint.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                problems.append(f"{tester['id']}: no readable fingerprint.json")
    comparison = {}
    for scenario in campaign["scenarios"]:
        teams = prints.get(scenario["id"], {})
        differing = differing_keys(teams) if len(teams) > 1 else {}
        comparison[scenario["id"]] = {"teams": len(teams), "differing": sorted(differing)}
        if len(teams) < 2:
            problems.append(f"{scenario['id']}: fewer than two teams produced a fingerprint, nothing to compare")
        if differing:
            draft = results / f"divergence-{scenario['id']}.md"
            draft.write_text(_divergence_draft(scenario["id"], differing), encoding="utf-8")
            problems.append(f"{scenario['id']}: {len(differing)} key(s) differ between teams; issue draft in {draft.as_posix()}")
            if open_issues:
                address, problem = open_issue(scenario["id"], draft)
                issues += [address] if address else []
                problems += [problem] if problem else []
    summary = {"testers": rows, "findings": len(merged), "scenarios": comparison, "issues": issues,
               "problems": problems}
    (results / "findings.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (results / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (results / "summary.md").write_text(_summary_text(summary), encoding="utf-8")
    return summary, problems


def _summary_text(summary: dict) -> str:
    lines = ["# Field campaign summary", "",
             f"{len(summary['testers'])} testers, {summary['findings']} findings before grouping.", "",
             "| Tester | Group | Report | Transcript | Outcome | Blocker | Major | Minor | Suggestion |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in summary["testers"]:
        lines.append(f"| {row['id']} | {row['group']} | {'yes' if row['report'] else 'MISSING'} | {row['log']} | "
                     f"{row['outcome']} | "
                     + " | ".join(str(row[severity]) for severity in SEVERITIES) + " |")
    lines += ["", "## Same scenario, several teams", "",
              "The scripted part is deterministic, so the threshold is zero: any key that differs is a defect.", ""]
    for scenario, data in summary["scenarios"].items():
        outcome = "identical" if not data["differing"] else "DIFFER on " + ", ".join(data["differing"])
        lines.append(f"- {scenario}: {data['teams']} team(s) compared, {outcome}.")
    lines += [f"- Issue opened: {address}" for address in summary.get("issues", [])]
    lines += ["", "## To settle before the campaign counts", ""]
    lines += [f"- {problem}" for problem in summary["problems"]] or ["Nothing: every tester reported and no scenario diverged."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List the thirty testers.")
    for name, text in (("prepare", "Create the testers' folders, the commands and the shared repository."),
                       ("cohorts", "Play each scenario's scripted part in several folders and compare."),
                       ("collect", "Check the reports, merge the findings, compare the scenario teams.")):
        action = actions.add_parser(name, help=text)
        action.add_argument("--out", required=True, type=Path, help="Campaign folder, outside the repository.")
        if name == "cohorts":
            action.add_argument("--teams", type=int, default=3, help="Folders per scenario (default 3).")
        if name == "collect":
            action.add_argument("--open-issues", action="store_true",
                                help="File each divergence draft as a GitHub issue with gh, in this checkout's repository.")
    one = actions.add_parser("brief", help="Print what one tester is asked to do.")
    one.add_argument("tester")
    one.add_argument("--out", required=True, type=Path, help="Campaign folder given to prepare.")
    args = parser.parse_args()
    try:
        if args.action == "list":
            campaign = load_campaign()
            for row in testers(campaign):
                print(f"{row['id']:<14} {row['group']}")
            problems = campaign_problems(campaign)
        elif args.action == "prepare":
            record = prepare(args.out)
            print(f"Prepared {len(record['testers'])} tester folders in {args.out.resolve().as_posix()} at commit {record['commit'][:12]}.")
            problems = []
        elif args.action == "brief":
            print(brief(args.tester, args.out))
            problems = []
        elif args.action == "cohorts":
            result = cohorts(args.out, args.teams)
            problems = []
            for scenario, data in result.items():
                if data["differing"]:
                    problems.append(f"{scenario}: differs on {', '.join(data['differing'])}")
                else:
                    print(f"{scenario}: {args.teams} teams, {data['keys']} keys, identical.")
        else:
            summary, problems = collect(args.out, args.open_issues)
            for address in summary["issues"]:
                print(f"Opened {address}")
            print(f"{len(summary['testers'])} testers, {summary['findings']} findings. "
                  f"Summary: {(args.out.resolve() / 'results' / 'summary.md').as_posix()}")
    except ValueError as error:
        print(f"field.py: {error}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"field.py: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
