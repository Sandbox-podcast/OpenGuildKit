# Project Storybook and company design system

A team can give its project a Storybook, show the components its company already approved next to its own, let the Design brain cite a story in a precise state, and derive a design system from an application it already has. The OpenGuildKit CLI does not run npm and never opens the network. It writes one configuration file, reads the `index.json` files that Storybook builds, and records the stories the boards can cite. The team runs npm and Storybook.

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

The URL may not carry a user name or a password: the refs file is committed, so the command refuses `https://user:password@...`. Let the company Storybook authenticate the browser with its own sign-in.

When the configuration folder has no `main` file yet, the command prints this minimal `.storybook/main.ts`, which loads the refs file. It needs `@storybook/react-vite` and `@storybook/addon-docs`, which `npm create storybook` installs. It was not built with Storybook when written: run `npm run build-storybook` to check it in the project.

```ts
import type { StorybookConfig } from '@storybook/react-vite';
import refs from './openguildkit-refs.json' with { type: 'json' };

const config: StorybookConfig = {
  framework: '@storybook/react-vite',
  stories: ['../src/**/*.mdx', '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)'],
  addons: ['@storybook/addon-docs'],
  refs,
};
export default config;
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

## Extract a design system from an existing application

A team that already has a React application can derive a design system from the code it is allowed to reuse. The extraction reads `.tsx`, `.jsx`, `.css` and `.scss` files, and the export lists of `.ts` and `.js` index files, and runs offline. It skips stories, tests, `node_modules` and build folders.

| Supported | Not supported |
| --- | --- |
| React function components: function declarations, arrow functions, `forwardRef` and `memo` | Class components |
| Props destructured in the first parameter, their literal defaults, and string-union types declared inline, in an interface or in a type alias of the same file | Props read from a `props` object, and types imported from another file |
| Named and default exports, export aliases such as `export { Card as Panel }`, and re-exports from an index file | Imports renamed by the screen that uses the component (`import { Panel as Box }`) |
| CSS and SCSS stylesheets | Vue, Angular and Svelte components, CSS-in-JS, utility classes such as Tailwind's |

`openguildkit storybook extract --help` gives the same list.

```bash
openguildkit storybook extract --src src/pages/RequestList.tsx --src src/components --preview screens/list.png
openguildkit storybook propose
# Edit .openguildkit/storybook/proposals.json: validate or reject, rename, group.
openguildkit storybook generate
npm run build-storybook
```

`extract` writes `.openguildkit/storybook/inventory.json`. Repeat `--src` to select the screens and folders to scan. The inventory lists:

- The components: exported functions or constants with a PascalCase name that render JSX, with their definition file and line, their props and literal defaults, and every use with its file and line.
- The variants: literal props such as `variant="danger"` or `disabled`, the default values of props a use omits, and each value of a typed string union such as `variant?: "primary" | "ghost"`, even when no screen uses it (`"basis": "type"`, a hypothesis tied to the definition line).

A component exported under another name, such as `export { Card as Panel }` or a re-export from `index.ts`, counts its uses under every name. The inventory keeps the name to import in `public`.

A `--src` folder outside the project, such as another repository next to it, is recorded relative to the project, such as `../other-app/src/Button.tsx`. When that path would climb to the drive or through the home folder, it is recorded as `outside:FOLDER/...` with a note, and `generate` writes no story for its components: copy them into the project first. No generated file holds an absolute path.
- The token candidates: colors in hex, `rgb()` or `hsl()` notation, font sizes, spacing, radii and font families, with the custom properties and Sass variables that name them and each `var()` that uses them.

An item seen only once is a `hypothesis`. `--preview` records a screenshot with its hash. The CLI does not read images, so a state the team or the agent reads from a preview goes into the proposals with `"basis": "preview"` and stays a hypothesis.

`propose` writes `.openguildkit/storybook/proposals.json`. Each component, variant and token has a `status` (`proposed`, `validated` or `rejected`) and a `name`. Components found under `pages`, `screens`, `views` or `routes` are marked `"kind": "screen"`. To group variants, set the props of one variant, such as `{"variant": "secondary", "size": "sm"}`, and reject the others. A token name is a dotted path that becomes the token's groups, such as `color.brand`. Running `propose` again after a new extraction keeps every status, name and props, and keeps the items no longer observed with `"observed": false`.

`generate` writes, for validated items only, into `src/design-system/` or `--out`:

- `design.tokens.json`, in the [Design Tokens Format Module 2025.10](https://www.designtokens.org/TR/2025.10/format/): colors in sRGB with their hex value, dimensions in `px` or `rem`, and font families.
- `COMPONENT.stories.tsx` in Component Story Format 3, one story per validated variant, or a `Default` story. The args are synthetic, such as `Sample label`, and never reuse the application's text. `parameters.openguildkit` gives the definition and the screens where each state was seen, with its confidence, to compare each story with the original screen.
- `index.ts`, which exports the validated components from where they are defined, under the name the proposal gives them: `export { Panel as Card }` for a component exported as `Panel`, `export { default as Shelf }` for a default export. Each story imports the same export.

Hashes in `.openguildkit/storybook/generated.json` let `generate` replace only the files it wrote. A file the team changed is kept, and a file no longer generated is left in place and listed. Import the application's global stylesheet in `.storybook/preview.ts` so that stories look like the screens.

The [example application](../examples/storybook-extract/) went through these steps on 20 November 2026, with the decisions listed in its README. `npm run build-storybook` with Storybook 10.6.6 built its 8 generated stories, and `npm run build` type-checked them with TypeScript 7.0.2 before the Vite 8.3.8 build. The extraction reads source text with patterns, not a full parser. It covers React function components, CSS and SCSS. Class components, CSS-in-JS and utility classes such as Tailwind's are not inventoried.
