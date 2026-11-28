# Project documentation and sharing

For: the owner of a project's documentation, and an administrator who shares pages with a client.

Completed tasks already hold what a reader needs: the brief, the expected behaviour, the acceptance criteria that were met, the delivery and the project version.
The project profile says what the project is and which rules apply.
`openguildkit docs export` turns the profile and the tasks you select into Markdown pages that [Documentalist](https://github.com/azerothl/documentalist) imports from a Git repository.

See [versions verified and reuse](#versions-verified-and-reuse) for the two local Documentalist runs on 2026-11-22.

## Export

```bash
openguildkit docs export --tasks request-status,request-history --output docs-site --version 1.4.0
openguildkit docs export --tasks request-status --output docs-site --version 1.4.0 --sections reference,blog --openapi openapi.yaml
```

Only tasks in the `done` or `done-with-reservations` state can be exported: their checks passed and their results are recorded.
The pages carry the brief, the behaviour and criteria that were met (each said once), how many checks passed, did not apply or stayed open, the disagreements between boards left open in the deliberation (or, without one, the objections that were not deliberated), the pull request or revision and the version.
They never carry the boards' reviews, the evidence paths, open questions or anything else from the local task records, and tasks you do not name are not exported.
The export checks the pages again: a credential that a brief, an answer or a result still holds is replaced with a placeholder, and an email address, a phone number or a bank account number is published with a warning on standard error.

| Folder | Documentalist tab | Content |
|---|---|---|
| `project/` | None with the three folders of the GitHub import | `overview.md`: the project's name, sector, stack, components with their stack, conventions, the rule packs in force with their version and rules, and the boards the exported tasks consulted |
| `reference/` | Reference | One page per task: behaviour, verification, source |
| `learn/` | Learn | A guide draft per task, marked for review before publication |
| `blog/` | Blog | A dated release note per task (`date` in the front matter and in the file name) |
| `openapi/` | None: the [OpenAPI import](#openapi) reads a URL | The file given with `--openapi`, committed so the Documentalist server can fetch it |

Each page carries `sidebar_position`, which gives the order of the pages in Documentalist.
`SUMMARY.md` and `README.md` at the root of the export list the pages for readers of the repository: with the three folders of the GitHub import they sit outside every imported folder, so Documentalist neither imports them nor reads them for the order (read in its code, `github.ts` and `import-order.ts`).
Paths depend only on the task ID and, for the blog, the completion date, so exporting again rewrites the same files: commit them, and the [synchronization](#synchronization) replaces each page found at the same path instead of creating a new one.
Pages of tasks you no longer select are removed.
The export refuses to write into a folder it did not create, or through a symbolic link that leads out of it.
`--output` and `--openapi` are paths inside the project, outside `.openguildkit/`, once symbolic links are followed; relative paths start at the project root.

The project page is written with the default sections, or with `--sections project`, and keeps one path, so a new export rewrites it.
It holds only what the profile and the active packs say: no component path, no check command, no local path and nothing from the tasks.
With the three folders of the GitHub import it is outside every imported folder and is not imported: keep it for readers of the repository, upload it by hand (a one-time copy, see [upload of a Markdown file](#upload-of-a-markdown-file)), or leave it out of `--sections`.

The export records the files it wrote in `docs-site/.openguildkit-export.json`.
That manifest is committed with the pages, so anyone can edit it: the next export only removes an entry that names a page it writes (`reference/`, `learn/`, `blog/`, `openapi/`, `SUMMARY.md`, `README.md`) and stays inside the output folder once `..` and symbolic links are resolved.
Any other entry, such as `../notes.txt` or an absolute path, is left in place and printed as `kept`.
A manifest whose `files` is missing or is not a list of paths is refused by name, and nothing is written.

Review the pages before committing them, especially the Learn drafts.
The [example](../examples/documentalist/) shows the export of the fictional request status task, with the inputs and a script that replays it byte for byte.

## Reproducible dates

`SOURCE_DATE_EPOCH`, following the reproducible builds convention, fixes the dates OpenGuildKit writes.
When it is set, its value in seconds since 1970-01-01 UTC replaces the current time in what a command records: task creation, board passes, decisions and completion, deliverable drafts, alert, tool and profile records, and so the dated blog page of an export.
A replay run with the same value therefore writes the same pages on any day:

```bash
SOURCE_DATE_EPOCH=1795176000 openguildkit task complete request-status   # recorded as 2026-11-20T12:00:00+00:00
```

A command that uses the fixed date says so once on stderr (`SOURCE_DATE_EPOCH is set: this command dates what it writes ...`), so a variable left in a shell, a build or a scheduled task does not go unseen.

What it does not decide: the decisions that depend on time follow the real clock, whatever the variable says.
`docs share add` refuses a last day that is not after the real date, `docs share check` reports a share whose last day is past on the real date, the length of a waiver is counted from the real date and its expiry judged on it, and the guard measures the age of an approval from the real time.
What a person decides is dated by the real time too, so that its age is measured on the same clock: the decision, the withdrawal of an approval, the clearance or waiver of a blocker and the authorization of an external action.
The replayed export keeps the dates the record holds.
The share register records the real time a share was added or revoked.
The ages of market dossier observations and of recorded Storybook indexes, which watched competitor sources are due for review, and the day after which a date you enter (an observation, a competitor change, the date of a board's evidence) counts as in the future are all counted from the real date too, and a market dossier records the real day a source was reviewed.
A build or a release script that exports the variable therefore neither hides a share to remove, a stale observation or a source to review, nor stretches a waiver.

Leave the variable unset in normal use.
A value that is not a whole number of seconds is refused.

## Install Documentalist if you need an instance

You can self-host Documentalist on your workstation or on a dedicated server.
A local instance is useful to review an export or rehearse import, sync and sharing with sample data.
A dedicated server can keep a portal available to the team and its readers.
Give a shared instance a reachable HTTPS address, persistent storage and backups.
Configure SMTP on the instance if you use email invitations.

Use the [local setup instructions](https://github.com/azerothl/documentalist#d%C3%A9marrer) or the [dedicated server deployment guide](https://github.com/azerothl/documentalist#d%C3%A9ployer-sur-la-dedibox) for your version.
The [dated verification report](../examples/documentalist/reports/2026-11-22.md) covers a local instance.

## Import into Documentalist

Three paths bring the export into a space.
Only the GitHub and GitLab imports keep the pages in step with the repository.

### From GitHub

An administrator opens Outils → Importer → "Depuis GitHub" (the "Importer depuis GitHub" dialog) and sets the repository and three folders: `docs-site/reference` as "Dossier docs" for Reference, `docs-site/learn` as "Dossier Learn" and `docs-site/blog` as "Dossier Blog".
With "Mettre à jour l'espace actuel" the pages go into the open space; otherwise the import creates a new space.
Outils → Intégrations only keeps the optional GitHub token.

The import reads github.com only: the repository is written `owner/repo` or as a github.com address, and there is no setting for a self-hosted Git server, a local repository or an archive (`github.ts`, lines 27-48 and 66-73).
A local address or a `file://` path is refused with "Dépôt invalide".
This path was not run on 2026-11-22, because the test instance had no access to github.com: the folder fields and the blog dating come from Documentalist's README and code.

### From GitLab

Outils → Intégrations → GitLab saves the host: gitlab.com or your own server (an internal host must be listed in the instance's `DOCUMENTALIST_PRIVATE_HOSTS`).
The import then takes one project, branch and folder.
With one folder there is no Learn or Blog: every page goes to Reference.
Imported with the folder `docs-site`, the root `README.md` and `SUMMARY.md` also become pages, both titled after the project.
It synchronizes like the GitHub import.
On 2026-11-22 it ran against a local stand-in that answered GitLab's API from a Git repository, not against a GitLab server.

### Upload of a Markdown file

"Importer un fichier Markdown" in Outils takes one file per pick and copies it into Reference, with the file name as title and no source path.
Every upload creates a new page, even for a file uploaded before: on 2026-11-22 a space went from 1 page to 4 with the three task pages, then to 5 when the updated reference page was uploaded again, the old copy staying.
Delete the old copy yourself, or use the GitHub or GitLab import.

### Synchronization

After a new export is committed, the GitHub or GitLab synchronization matches each page by space, source path and locale: a page found again keeps its ID and gets the new content, with no duplicate (5 pages and 3 categories before and after the sync of the 1.4.1 export).
Keep the same import locale from one sync to the next.
The sync reports every file as updated, changed or not.

A file missing from a new export deletes its page at the next sync; its category stays, empty.
When the file comes back, it is a new page with a new ID, so links to the old page break.

The sync runs when someone presses "Relancer sync", or while someone has the space open in the editor, at most once per interval (60 minutes by default).
The server never syncs on its own.
The portal keeps serving the last publication until someone presses "Publier" again: after a sync, publish to show the new pages.

### OpenAPI

The OpenAPI import (Outils → Intégrations → OpenAPI) takes a URL that the Documentalist server fetches, not a file: a public address, or a host listed in `DOCUMENTALIST_PRIVATE_HOSTS`.
Commit `docs-site/openapi/` and give the raw address of the file.
Each import adds an overview page and one page per operation at the root of Reference.
Importing the same file again adds them a second time (5, then 8, then 11 pages on 2026-11-22), and a sync neither updates nor removes them: before importing a new version, delete the pages of the previous one.

## Versions verified and reuse

On 2026-11-22, a local macOS instance at [`947429b`](https://github.com/azerothl/documentalist/tree/947429b19da6) on Node.js 26.13.0 exercised synchronization with a GitLab stand-in, OpenAPI import and magic-link sharing.
A separate local Windows run used Node.js 22.20.0 and imported three pages from the public OpenGuildKit example on GitHub.
Its forced sync kept the same three pages and IDs.
The [dated report](../examples/documentalist/reports/2026-11-22.md) records the steps and versions for both runs.

On 2026-11-23, reader end dates and `share verify` were checked on macOS with Node.js 26.13.0 against two local builds: [PR #25](https://github.com/azerothl/documentalist/pull/25) as it stood that day (`7dbc66e`, two commits on top of `947429b`), on HTTP and behind HTTPS, and `947429b` itself.
PR #25 was merged on 2026-11-24 as [`46976a9`](https://github.com/azerothl/documentalist/commit/46976a97397718061a218d8a72ddc6d9b47fd421), with no release yet; the routes and fields `share verify` reads were compared with that commit's code, not run against it.
Invitations and open sessions created on `947429b` kept working after the upgrade, with no end date until one was set.
The [report](../examples/documentalist/reports/2026-11-23-expiry.md) lists the steps.
Repeat the comparison on the version you deploy.

Reuse conditions, as of 2026-11-22: the repository has no licence file, now or in its history; GitHub reports its licence as `null`; `package.json` is marked private and has no `license` field; the README calls Documentalist free software that can be self-hosted, without naming a licence.
OpenGuildKit does not redistribute its code.
Ask its author before any redistribution or reuse of it.
The exported Markdown belongs to your project.

Reader end dates need Documentalist at [`46976a9`](https://github.com/azerothl/documentalist/commit/46976a97397718061a218d8a72ddc6d9b47fd421) or later, the merge of [PR #25](https://github.com/azerothl/documentalist/pull/25) into `main` on 2026-11-24.
No tag or published release contains it yet (`package.json` still says 0.1.0 and the v0.1.0 release is a draft): deploy that commit or a later one, and name the commit.
From it, an invitation in magic-link mode can carry a last day of access per address and space.
The day is included, in UTC: the access ends at 00:00 UTC the next day, for unused links, open sessions and new link requests alike, and "Retirer l'accès" still ends it at once.
Invitations made before the upgrade keep working with no end date until someone sets one in the reader settings: after upgrading, give each address the last day that `share list` shows for it.
An instance older than `46976a9` has no end date at all: there, `share check` is the only reminder and "Retirer l'accès" the only way to end an access.
On 2026-11-24, `npm test` (36 of 36) and `npm run test:http` (12 of 12, including a reader's old link, open session and new request after the last day) passed at `46976a9` on macOS with Node.js 26.13.0.
Its tree is the same as `8e36a7c`, the commit of the browser run and of the compatibility run on data created at `947429b` reported in PR #25.
A dedicated server with real SMTP was not tried.

## Read published pages through MCP

Documentalist's [MCP server](https://github.com/azerothl/documentalist/blob/947429b19da6f4e409738fd195960ae99e99c4ef/README.md#L240-L267) lets agents list, search and read published pages.
Set `documentalist.domain` to your instance's HTTPS hostname.
OpenGuildKit builds the endpoint as `https://<hostname>/mcp`.

```bash
openguildkit tools plan documentalist --host codex --set documentalist.domain=docs.example.org
openguildkit tools apply documentalist --host codex --set documentalist.domain=docs.example.org
```

For private publications, an administrator issues a scoped MCP key in Documentalist.
Put it in the host's environment and add `--token-env documentalist=DOCUMENTALIST_MCP_TOKEN` to the plan and apply commands.
Public publications can be read without a key.
Use `--host claude-code` for Claude Code with the same settings.

The MCP connection is read-only.
Import and publication stay in Documentalist, as does granting or revoking portal access.

## Share a deliverable

Documentalist grants access to a whole space, per email address.
A portal is public, protected by a shared code, or limited to invited addresses with magic links: choose the "lien magique" mode in the space's Paramètres before the first invitation.
Magic links need SMTP on the instance (`DOCUMENTALIST_SMTP_URL` and `DOCUMENTALIST_EMAIL_FROM`); without it the invitation is refused.
A link lasts 24 hours and works once, and a reading session lasts up to 8 hours.
A Documentalist that includes [PR #25](https://github.com/azerothl/documentalist/pull/25) also enforces an optional last day per invited address and space; an earlier one, such as `947429b`, keeps the access until an administrator removes it.
"Retirer l'accès" removes every link and session of that address for the whole space.
The portal does not share a single page independently.

OpenGuildKit keeps the register of what you shared, with whom, through which space and until when:

```bash
openguildkit docs share add --deliverable docs-site/reference/request-status.md --recipient client@example.org --until 2026-12-31 --portal https://docs.example.org/p/support-portal --by CM
openguildkit docs share list
openguildkit docs share check        # exit code 1 while an access past its last day is not recorded as revoked
openguildkit docs share revoke --id ID --by CM
```

**The perimeter is the space.** `--portal` is the address of the shared space's portal, `https://HOST/p/SPACE` (a page address in that space works too); an address without `/p/SPACE` is refused, and so is one with a user name, a password or a token in its query: the register keeps the address as written.
`share add` records the space and prints it, and `share list` shows it after each deliverable.
A reader invited for one page sees every published page of the space that is not hidden: on 2026-11-22, a reader invited for one reference page saw 11 pages and 3 categories.
To share one deliverable with its own reader list, [give it a dedicated space](#share-one-deliverable-in-an-isolated-space).
`http` is accepted only for an instance on this machine (`localhost`, `127.0.0.1` or `::1`), such as a local test instance.

**`--until` records the intended last day.** Set the same day in the portal's reader settings ("Dernier jour d'accès") when the instance supports it: the day is included, in UTC, and the access ends at 00:00 UTC the next day, for links already sent, open sessions and new link requests alike.
On an earlier instance, remove the invitation by hand after the last day.
From the next UTC day, when the portal ends the access, `share check` lists the share as expired and names the addresses to review; it reads the register only and keeps this reminder even after a portal observation.
An address that another running share gives the same space is listed as kept, with the last day of the share that ends last; a share whose addresses are all kept is `covered`.

### Compare the register with a portal

`share verify` compares the register with the reader settings of one space, on request:

```bash
openguildkit docs share verify --portal https://docs.example.org/p/support-portal --user editor@example.org
openguildkit docs share verify --portal http://127.0.0.1:3000/p/support-portal --user editor@example.org --json
```

It asks the password of a Documentalist editor or administrator account at the terminal (it refuses to run without one, and never reads a password from an argument, a file or the environment), signs in, reads the space list and that space's invitations, then signs out.
It changes nothing in the portal and saves no credential.
It is the only command that opens a network connection, and only to the address given with `--portal`.

For each address of the register's shares in that space, it prints the register's last day, the portal's, the state of the portal's access (`open` or `ended`) and `matches` or `mismatch`, and for a mismatch what to change in the portal:

```text
127.0.0.1:3000/p/expiry-portal: documentalist-api at 2026-11-23T13:05:21+00:00
Invitation settings only; verify actual reader access separately.
  reader@example.test: register until 2026-12-31; portal until 2026-12-15 (open); mismatch
    Change the last day for reader@example.test in the reader settings of space 127.0.0.1:3000/p/expiry-portal from 2026-12-15 to 2026-12-31, or correct the register.
```

- **Several shares to the same address and space** are one access in Documentalist: the register's last day is the latest of the shares not revoked, and that is the day to set in the portal.
  `share add` names it when it warns about the second share.
  An address whose shares are all revoked must not be invited any more.
- **An invitation without a last day** in the portal is open with no end: it is a mismatch against a share that has one.
  Invitations made before the portal supported end dates have none until someone sets it.
- **The source is printed:** `documentalist-api` when the portal's settings were read, `local-register` when they could not be.
  Exit code 0 only when every row matches.
- **An earlier instance or one that does not answer** leaves the register as it is: the command prints why (no end dates on that version, no answer, a refused account, a certificate it cannot verify), marks each address `unverified`, prints the action to take by hand (on a version without end dates, remove the access after the last day with "Retirer l'accès", then `share revoke`), and exits 1.
  `share list` and `share check` keep working.
- **What it shows is the settings, not a reader's session.** On 2026-11-23 the settings and a real reader's browser agreed before and after the last day ([report](../examples/documentalist/reports/2026-11-23-expiry.md)); the portal's own tests check old links, open sessions and new link requests after the end.
- `share list` repeats the last observation of each share's space, with its time and source: it can be outdated.
  It is kept in `.openguildkit/shares/portal-observations.json`, ignored by Git like the register ([personal data](personal-data.md)).

Configuration:

| Instance | `--portal` | Notes |
|---|---|---|
| On this machine | `http://127.0.0.1:PORT/p/SPACE` (or `localhost`, `::1`) | Use the exact address of the instance's `DOCUMENTALIST_URL`: Documentalist refuses a sign-in from another origin (HTTP 400, "Origine de la requête refusée"), so `localhost` does not reach an instance configured as `127.0.0.1`. An instance started for production over http needs `DOCUMENTALIST_COOKIE_SECURE=false`, or its session cookie does not come back (HTTP 401 after the sign-in). |
| Dedicated server | `https://HOST/p/SPACE` | HTTPS is required off this machine. The certificate must be trusted by Python's default store; for an internal authority, point `SSL_CERT_FILE` at its certificate. |

The account needs access to the space and the reader settings (an editor or administrator; a viewer is refused).
Documentalist allows 10 sign-ins per account in 10 minutes, and 30 unauthenticated requests per route in a minute.
The register and the portal both count the last day in UTC: the access ends, and `share check` lists the share as expired, at 00:00 UTC the next day.
East of UTC that is a few hours before the local day ends, west of UTC a few hours after.

**One access per address and space.** Two shares of the same address and space are one access in Documentalist.
`share add` warns on stderr when a running share already gives one of its recipients the same space.
`share revoke` reminds you that "Retirer l'accès" covers the whole space, and prints a `share revoke` command for each other share that gives one of the same addresses that space: one removal in the portal ends them all, so record each one.

`--deliverable` is a path inside the project; the register records it relative to the project root, written with `/` and with links resolved (`./d.md` and the absolute path of `d.md` are the deliverable `d.md`), so it holds no local path.
A path outside it once symbolic links are followed, or under `.openguildkit/` (task records and other state the team does not share), is refused.
It names the deliverable you share: an existing file, or the folder that `docs export` wrote (the one that holds `.openguildkit-export.json`); a path that does not exist, or another folder, is refused.
The owner chooses the deliverable, the recipients and the last day of access (`YYYY-MM-DD`, after today and at most 366 days ahead, on the real clock) before inviting them in the portal.
A revocation records who removed the access and when; a second revocation of the same share is refused, so the first record stays.

**What the instance records.** A compatible space's Paramètres list invited addresses and their optional expiry dates, but not the individual pages shared.
The activity log records the time and the administrator of each invitation and removal, not the address.
Keep the register to record which deliverable was shared and why each address has access.
Older instances record no expiry date.

What OpenGuildKit does not do: it creates no magic link and revokes no access in Documentalist.
Inviting the recipients and pressing "Retirer l'accès" happen by hand in the space's reader settings; `share add` and `share revoke` only record that you did it.
Keep the portal and the register in step.

What `share check` reads: only the local register, `.openguildkit/shares/shares.json`.
It lists every share and exits with code 1 when a share that is not recorded as revoked has a last day of access before today and an address to remove.
It does not contact Documentalist, so it cannot see an access removed in the portal without `share revoke`, nor an invitation sent without `share add`.
The register is ignored by Git because it contains email addresses ([personal data](personal-data.md)): the check runs where the register is, usually the owner's machine (for example from a scheduled task there), not in CI on a fresh clone, where it finds no share and passes.
Writes to the register hold the project lock, so shares recorded at the same time are all kept.
The boards' reviews stay in the local task records and are never part of a share; Documentalist does not publish its own comments either.

### Share one deliverable in an isolated space

Documentalist cannot limit a reader to some pages of a space: once a reader's session is open, every published page of
the space that is not hidden is in the portal's navigation, search and direct links (read in its code: the portal page
`src/app/p/[spaceSlug]/[[...path]]/page.tsx` checks the space with `portalAllowed` in `src/lib/auth.ts`, then hands the
whole published snapshot to the portal, whose search runs in the browser over those pages).
"Masquer du site" hides a page from
every reader of the space, not from one.
To give a deliverable its own reader list, give it its own private space, and
record that space as dedicated to it:

```bash
openguildkit docs share add --deliverable docs-site/reference/request-status.md --recipient client@example.org --until 2026-12-31 --portal https://docs.example.org/p/request-status --by CM --dedicated-space
```

What `--dedicated-space` does, in the register only:

- `share add` refuses it when the register already holds a share not revoked of another deliverable in that space,
  and, once recorded, refuses any share of another deliverable in that space, with or without the option.
  A new
  share of the same deliverable in that space is dedicated too, so the space stays dedicated after the first share is
  revoked.
  Shares are compared by space (`HOST/p/SPACE`) and by deliverable path (`d.md` and `./d.md` are one).
- Without the option, `share add` warns on stderr when the space already carries another deliverable, and `share list`
  and `share check` print, under each share, the other deliverables its recipients can read in the same space.
- `share check` exits with code 1 when a dedicated space carries another deliverable in the register, which only a
  hand edit of the register can cause.

What it does not do: OpenGuildKit does not see what the space publishes.
A page imported, synchronized or published in
that space by hand, or a revoked share whose page was left in it, is not in the register.
Existing shares and spaces
keep working as before: a share recorded without the option is not dedicated, and nothing is refused for it.

1. Import only that deliverable into a new space.
   Check the pages and sections
   included in the publication after each import or sync.
2. Select magic-link access and use a test invitation to publish and verify the
   space.
   Check the contents and search from that separate reader session.
   Invite the intended readers and record the dedicated portal with
   `docs share add --dedicated-space`.
3. Republish updates in the same space when the audience stays the same: a new
   publication replaces the whole snapshot, so every invited reader sees every
   page published at that moment.
   When a copy replaces a document in another
   space, review the intended readers for the destination, then remove the old
   copy from the source publication and verify its former URL.
   Documentalist
   has no move of a page between spaces: a page reaches another space only as a
   copy (import or upload), and the readers of the source keep the last
   publication of the source until it is published again.
   If access to the
   entire source space must end, revoke it in Documentalist and record the
   removal in OpenGuildKit.
4. To end one share, remove the reader in that deliverable's space and record
   the revocation against its share ID.
   "Retirer l'accès" removes that address's
   links and sessions for that space only: if the reader has access to other
   spaces, verify those portals remain available.

See the [two-space validation and remaining cases](../examples/documentalist/reports/2026-11-23-space-isolation.md)
and the [options considered for issue #266](documentalist-sharing-scope.md), with the open questions for the maintainers.
