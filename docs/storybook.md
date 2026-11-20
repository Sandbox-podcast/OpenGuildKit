# Project Storybook and company design system

A team can give its project a Storybook, show the components its company already approved next to its own, and let the Design brain cite a story in a precise state. The OpenGuildKit CLI does not run npm and never opens the network. It writes one configuration file, reads the `index.json` files that Storybook builds, and records the stories the boards can cite. The team runs npm and Storybook.

## Create the project Storybook

The reference stack is React, Vite and TypeScript. These commands were run on 20 November 2026 with Node.js 26.13.0 and npm 11.20.0. They installed React 19.3.1, Vite 8.3.8, TypeScript 7.0.2 and Storybook 10.6.6 with `@storybook/react-vite` and `@storybook/addon-docs`.

```bash
npm create vite@9.3.4 my-app -- --template react-ts --no-interactive
cd my-app
npm install
npm create storybook@10.6.6 -- --yes --no-dev --features docs
npm run build-storybook
```

In an existing React and Vite project, run only the last two commands. `npm run storybook` starts the development server on port 6006. `npm run build-storybook` writes `storybook-static/`, a static site to publish or open with any web server. Its `index.json` lists every story. Storybook collects usage data by default. Set `STORYBOOK_DISABLE_TELEMETRY=1`, or `core: { disableTelemetry: true }` in `.storybook/main.ts`, to turn it off.

## Reference the company design system

When the company publishes its Storybook, compose it into the project's Storybook:

```bash
openguildkit storybook compose company --url https://design.example.com --title "Acme design system"
```

The command adds or updates the `company` entry in `.storybook/openguildkit-refs.json`, a file it manages, and keeps the other entries. `--remove` deletes an entry. It never edits the team's configuration. If `.storybook/main.ts` does not import the file yet, the command prints the two lines to add:

```ts
import refs from './openguildkit-refs.json' with { type: 'json' };
// inside the exported configuration object:
  refs,
```

The project's Storybook then shows the company's components, stories and documentation pages in a separate section of its sidebar. The browser loads them from the published Storybook. It sends credentials, so that server must answer the project's origin with `Access-Control-Allow-Origin` set to that origin and `Access-Control-Allow-Credentials: true`. A wildcard origin is refused.

When the company distributes a component library, install it with npm as for any dependency and write the project's stories against it. Its `package.json` is enough to check the versions it expects.

## Compare and record the stories

```bash
npm run build-storybook
openguildkit storybook import --company-index company/index.json \
  --library node_modules/@acme/design-system/package.json
```

`--company-index` takes the company Storybook's `index.json` or its static folder, downloaded or built by the team. `--project-index` defaults to `storybook-static/`. Storybook 7 and later write the format the command reads (`"v": 4` or `5`). It reports:

- The components and stories of each Storybook, and the theme sources: library exports and Storybook pages that name a theme, tokens, colors or styles.
- Project components matched by name in the company Storybook, and those left to map.
- Conflicts to resolve: a story ID or a title used by both.
- The library's peer dependencies and shared dependencies against the project's versions. The command reads the installed version under `node_modules`, or the lowest version the project's range allows. A row is `ok`, `partial`, `conflict`, `duplicate` (two copies would be installed), `missing`, `optional` or `unknown`. Styling libraries are marked.

The command records the known stories in `.openguildkit/storybook.json`: for each index, its source, its SHA-256, the date and the stories with their title. A new import replaces the entry of the same index and keeps the others. It writes nothing else, so the project's stories and configuration stay as they are. Commit the record so the whole team sees the same stories.

## Cite a story in a review

When the record exists, `task consult` adds the story IDs to the consultation scope, and the Design brief explains how to cite them. A Storybook ID names one story, so one state: `storybook:example-button--disabled` points to a project story, `storybook:company_components-button--disabled` to a composed one, as in the Storybook URL `?path=/story/ID`. The CLI refuses a story the project did not record. Import again after adding stories.
