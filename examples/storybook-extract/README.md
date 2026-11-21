# Extract a design system from a small application

These sources form a small fictional support portal: a `Button`, a `StatusBadge`, two screens that use them with synthetic requests, and the stylesheets they share. They show what `openguildkit storybook extract` finds and what `generate` writes. Only the sources are kept here, without `package.json`, lockfile or `node_modules`.

The test suite runs the extraction on these files. To build the result with Storybook, copy `src/` into a React, Vite and TypeScript project that has a Storybook ([docs/storybook.md](../../docs/storybook.md)), with `src/main.tsx` rendering `App`, then run the steps in that project:

```bash
openguildkit storybook extract --src src
openguildkit storybook propose
```

The run of 20 November 2026 validated `Button` and `StatusBadge`, rejected the three screens, and kept these variants: Button `primary`, `secondary`, `danger` and `disabled`, a "Secondary small" story made from `{"variant": "secondary", "size": "sm"}`, and StatusBadge `open`, `closed` and `waiting`. It validated the colors `#0a66c2`, `#1f2933` and `#c62828` (renamed `color.danger`), the spacing `8px` and `16px`, the radius `6px`, the font size `0.875rem` (renamed `font-size.control`) and the font family. After `openguildkit storybook generate`, `import '../src/styles/theme.css';` was added to `.storybook/preview.tsx`, and `npm run build-storybook` built the 8 stories with their synthetic labels.
