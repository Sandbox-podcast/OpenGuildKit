# 2. Scope the task

For: the agent that scopes a task, and the person who answers its questions.
Step 2 of the [task workflow](../workflow.md).

`task questions ID` prints a JSON object: `questions`, the questionnaire; `follow_ups`, the follow-up questions still to ask, each with its `id` and `prompt` (and its `choices` for `concerns`); and `open_points`.
Without `--answers` the last two are empty.
With `--answers FILE --follow-ups`, it prints only `follow_ups` and `open_points`, without the questionnaire again: about 300 bytes for a small bug instead of 5 KB.
The agent asks the person, in their language, and confirms any answer it inferred from the brief.

| Key | Question | Choices |
|---|---|---|
| `kind` | What are you asking the team to do? | `feature`, `bug`, `maintenance`, `decision`, `other`, `unsure` |
| `surface` | Which areas will this task affect? Several can apply. | `customer`, `service`, `infrastructure`, `business`, `other`, `unsure` |
| `data` | What is the most sensitive data this task may access or change? | `none`, `internal`, `personal`, `regulated`, `unsure` |
| `research` | What evidence can the boards consult? | `local`, `public`, `unsure` |
| `concerns` | Does the task involve any of these? Several can apply. | `money`, `ai`, `people-decisions`, `credentials`, `none`, `unsure` |
| `context` | What acceptance criteria, constraints or other context should the boards know? | Free text |

`context` is optional, except when any answer is `other`.
`concerns` is required for every new consultation: `money` covers prices, payments, invoices, payroll or spending; `ai` an AI model or LLM that produces answers or content; `people-decisions` software that scores, ranks or decides about individual people, such as hiring, credit or a price per person; `credentials` secrets, keys, tokens or passwords; `none` none of these.
`none` and `unsure` stand alone.
`unsure` keeps the rules of every topic open, and the boards of every topic (legal, data, security, finance and devops) review the task, so that the rules asked and the boards consulted say the same thing.
Without `concerns`, `task questions ID --answers FILE` lists it in `follow_ups` with its choices, and `task consult` and `task route` refuse the answers and name the choices.
A task consulted before the question was required keeps its recorded answers: `task route ID` without `--answers` and its passes still work, and its rules read the missing answer as open, like `unsure`.
`surface` takes a list, for example `["customer", "service"]` for a change to a screen and the service behind it; a single value is still accepted.

## Follow-up questions and open points

Save the first answers and run `task questions ID --answers answers.json --follow-ups`.
The CLI names the questions that these answers call for and lists the points still open:

| Key | Asked when | Question |
|---|---|---|
| `outcome` | feature, bug, maintenance, other, unsure | The observable result, the expected behaviour and how to reproduce a defect, or what must keep working |
| `affected` | feature, decision, other or unsure work, customer or business areas, personal or regulated data | Who is affected: users, customers, teams or partners |

| `options` | decision | The options on the table and what would make you choose one |

In a project with components, `answers.json` can include `"components": ["web"]`, with the IDs from the project profile.
It limits the task to those components and to what is project-wide: the packs and patterns brought for other components leave the scope, the stack shown is theirs, and a check command that runs from another component's folder (`cd services/api && python3 -m pytest -q`, as `init` proposes it, or a folder inside that component) leaves the scope, `task verify` and the closing.
A command without a leading `cd FOLDER &&` stays asked of every task.
The board of each declared role whose subjects the component's stack names joins the consultation with the reason, such as `frontend` for a component on React.
A path of the brief inside a component's folder (`apps/web/src/price.ts`) brings that board too and puts that component's packs first in each pass, but only the answer narrows the scope and the checks.
Leave `components` out to consult for the whole project.

A question is essential for the cases where the boards cannot review without it: the outcome of a feature or a bug, who is affected by a customer-facing change, the options of a decision.
A short brief, an `unsure` answer or an unanswered essential question is an **open point**.
Open points do not block the consultation: they appear in it, each board says how they affect its recommendation, and the decision brief repeats them.
A well-described local bug gets no question about customers or options.

```json
{
  "kind": "feature",
  "surface": "customer",
  "data": "personal",
  "research": "local",
  "concerns": ["none"],
  "context": "Signed-in users see the status and next step of their own support requests."
}
```

`task consult ID --answers answers.json` validates the answers, selects the boards and prints the consultation request in Markdown.
Without `--answers`, the CLI asks the questions in the terminal.
`task brief ID` prints the same request again later.
To correct the brief, pass `--brief "REVISED BRIEF"` or `--brief-file FILE` to the next consultation: on a draft, during the consultation (the passes start over, as at every new consultation), or after a request for changes.
After a request for changes, the task keeps its previous brief and decision in the round history, and the next decision brief and approval prompt show why changes were requested.

The consultation stays short so that an agent can keep it in context: the task and its answers, the project scope once (stack, components, packs named with their number of rules, conventions, checks, host controls), the open points, and one line per board with why it was selected.
It does not repeat the rule texts (`AGENTS.md` names each rule by its ID and leaves its text out, as it leaves out the verification and the sources of the packs: a pass prints the rules that concern the task), nor each board's brief, which its pass prints.
What it leaves out stays available: `task brief ID --pack PACK` prints one pack in full, `task brief ID --scope` prints the whole scope as JSON with every rule text, `task brief ID --board BOARD` prints a board's pass, and `openguildkit brains --id BOARD` the board's full reading list.
For a bug, when the brief names a file or a function (`src/export.js`, `exportCsv()`, `` `toRow` ``) that the project does not contain, the consultation says so in one line, so that the boards check the brief before reviewing code that is not there.

## Assumptions not confirmed

What scoping takes for granted without anyone confirming it goes in `assumptions`, a list of sentences, apart from the answers the person gave (#436):

```json
{
  "kind": "feature",
  "surface": "customer",
  "data": "personal",
  "research": "local",
  "concerns": ["none"],
  "assumptions": ["Requests are linked to accounts by the customer ID.", "Support agents keep their current view."]
}
```

- **Asking.** While `outcome` or `affected` is asked and still empty, `task questions ID --answers FILE --follow-ups` lists `assumptions` in `follow_ups`: what is assumed in their place is worth writing down.
  At the terminal, `task consult` asks it after the other follow-ups; Enter skips it.
- **Checking.** Anything other than a list of non-empty sentences is refused with the shape to write.
  An empty list records nothing.
- **The boards.** The consultation, each board pass and the handoff list them, numbered, under `Assumptions not confirmed (N)`.
  A pass's entry has `"contested_assumptions": []`: a board that disputes one adds `{"assumption": 2, "reason": "..."}`, with the number of a listed assumption.
  Another number, or the key in a task without assumptions, is refused.
- **The person.** `task challenge`, `task decision-payload` and the approval prompt of `task decide --approve` print `Assumptions not confirmed (N)` apart, before the request to type the task ID, the contested ones first with the boards that contest them and why.
  The JSON of `task challenge` has them under `assumptions`.
  Nothing blocks: approving accepts them as they are.
- **What does not change.** Answers without `assumptions`, and every task recorded before, read and print as before.

## How boards are selected

Answers route to boards first:

| Answer | Boards |
|---|---|
| `kind: feature` | product, engineering, qa |
| `kind: bug` | engineering, qa |
| `kind: maintenance` | engineering, qa |
| `kind: decision` | product |
| `kind: unsure` | project-management |
| `surface: customer` | product, design, marketing |
| `surface: service` | engineering, performance |
| `surface: infrastructure` | devops, performance |
| `surface: business` | project-management |
| `data: internal`, `personal`, `regulated` or `unsure` | security |
| `data: personal` or `regulated` | legal |
| `concerns: money` | finance |
| `concerns: ai` | data, security, legal |
| `concerns: people-decisions` | legal, data, security |
| `concerns: credentials` | security, devops |
| `concerns: unsure` | legal, data, security, finance, devops: every topic stays open |

Then each board's `triggers` are matched as whole words in the brief and context.
Matching ignores case, accents and the kind of apostrophe, accepts a regular plural on each word (`jalon` matches "jalons") and does not look inside hyphenated words ("e-commerce" does not contain `commerce`).
When triggers overlap, the longest phrase wins: "performance budget" selects `performance`, not `finance` through `budget`, and "DORA metrics" selects `devops`, not `security` through `dora`.
Boards that share the exact same phrase are all selected.
A board's own shorter phrase never cancels its longer one, so "DORA lead time for changes" stays with `devops` through `dora lead time` and `lead time for changes`, and `legal` does not read it as the DORA regulation.
A few job titles, such as "backend engineer", claim their words for no board: "Hire three backend engineers" selects `hr`, not `engineering`.
"Reduce checkout latency" adds `performance`; "RGPD" adds `security`.

A trigger preceded in its clause, within five words, by a negation selects nothing: "no payments", "without personal data", "sans paiement", "aucune donnée personnelle", "pas de changement d'interface utilisateur", "it does not touch the API", "nothing to do with payments".
The negating words are `no`, `not`, `without`, `never`, `nor`, `neither`, `none`, `nothing`, `cannot`, any word ending in "n't", `sans`, `pas`, `aucun`, `aucune`, `ni`, `jamais`, `non` and `rien`; "avoid" or "éviter" counts when a change follows ("avoid any changes to the pricing page").
A negation written after the subject counts too: "payments are out of scope", "paiements hors périmètre".
The items of a negated list are all excluded: "without touching personal data or secrets".
A clause ends at punctuation, a line break or "but"/"mais".
These are not read as negations, so the board stays: "not only ... but also", "no more than", "sans doute", a double negation ("not without payments", "pas sans paiement"), and a negated verb of omission ("do not forget payments", "don't skip the payment step", "ne pas oublier les paiements").
An imperative "ignore" at the start of its clause sets its object aside: "Also ignore the competitors", "Ignorez les concurrents".
A short clause that opens with "without" or "sans" and goes on after a comma depends on what follows.
When the next clause starts with an instruction ("Sans les concurrents, ajouter le calcul des prix", "Without competitors, add the price calculation"), the subject is set aside.
When the next clause starts with anything else, a subject or a statement ("Sans paiement, la commande n'est pas validée", "Sans paiement, impossible de valider"), the subject may be what is needed: the board stays and its reason says so.
An instruction is a French infinitive or imperative after "sans", or a common English imperative (add, fix, update, change and the like) after "without".
When the reading is uncertain, the board is kept.
The same rule applies to the subjects below.
Each reason quotes the passage that selected the board, as written, from the brief or from one answer at a time: `finance: Brief mentions 'payment': "Adyen for card payments"`.

When the profile declares roles (`roles` at `init`), the stack selects their boards too: `frontend` for a task whose surface is `customer` when the project's stack names React, Vue, Angular, Svelte or Next.js; `backend` for a `service` task when it names Django, Rails, Laravel, Spring Boot or FastAPI;
and, for a component the task names or whose path its brief cites, each declared role whose subjects the component's stack names (`devops` for Terraform).
The words compared are the board's triggers.
When the task names the people it serves, that board is selected too.
The `affected` answer names them anywhere ("Support managers who paste the weekly numbers"); the brief and the `context` name them within eight words after "for", "audience", "read by", "pour" or "public", so that every role of a list counts ("a ticket report for our support agents", "Audience: support team and customer-success managers").

Some subjects are recognised from the words of the brief as a whole, the same way as the `concerns` answers: an AI model or algorithm applied to applicants, employees, loans or credit adds legal, data and security; an LLM, chatbot or AI assistant adds data, security and legal; spending or a bill from a cloud or SaaS vendor adds finance.
When such a subject calls for a pattern the project has not selected, `task route` names it, for example `eu-ai-act-system` for software that ranks job applicants.

Only boards enabled in the profile are selected.
If nothing matches, the route says that no discipline was recognised and asks the requester to add the boards that apply with `--add`; `product` reviews the scope meanwhile, or the first enabled board by ID when `product` is disabled.

## Preview and adjust the boards

`task route ID --answers answers.json` shows the boards a consultation would select and why, without recording anything.
Under each board it lists the project's tools that board can query, connected or only listed in the profile.
When the brief names one of the project's tools, a line says which boards can query it.
Then come the boards the brief mentions as excluded, with the passage ("Mentioned as excluded: finance (no payments)"); the consultation repeats that line.
The boards the team expects (its declared roles, or the boards its profile lists) that were not selected each get a line with the reason and examples of the words that would select them.
The other enabled boards are counted on one line (`openguildkit brains` lists them).
Last come two commands: `task route` with `--add`, `--remove` and `--reason` to preview a change, and the complete `task consult` command that applies the options and answers file given to this `task route`.
A word that needs quoting goes between single quotes, in which neither a POSIX shell nor PowerShell (the form printed on Windows) expands `$` or a backtick, so the pasted command records the reason as typed; the commands `tools plan` and the web interface print are quoted by the same function.
`--json` gives the same under `excluded`, `not_selected` and `expected_not_selected`.
The requester can then change the list for this task:

```bash
openguildkit task consult ID --answers answers.json --add finance --remove marketing --reason "Exports are billed per page"
```

Each addition or removal needs a reason; the consultation records it under `adjustments`.
Only boards enabled in the profile can be added.
Only the requester decides to remove a board, and the decision brief and the approval prompt list every change with its reason.
A board selected by a `personal`, `regulated` or `unsure` data answer (security, and legal for regulated data) can be removed only with the approver's confirmation: the removal stays pending until the person approving types the board's name at the prompt, and approval is refused without it.

A project can make some reviews mandatory with `openguildkit profile add required-board security --by INITIALS --reason WHY`, which writes `"required_boards": ["security"]` in its profile.
These boards join every consultation and cannot be removed; `AGENTS.md` lists them under "Required reviews".
When a required board is not enabled for the project, the consultation stops and names it.
The requester can then name the person who will review instead, with `--delegate security=AM`: the brief tells the agent to prepare the review for that person, and the review entry carries that identifier in `reviewer`.

Each selected board gets a brief with its purpose, the routing reasons, its expertises, its questions and its source leads.
The request also carries a snapshot of the project scope: sector context, stack, resolved rule packs, conventions, checks and the research policy for this task.
