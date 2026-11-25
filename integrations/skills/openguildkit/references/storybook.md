# Storybook

Read this file when the project has a Storybook or the user wants the company's design system.

When the project has a Storybook or the user wants the company's design system, run `openguildkit storybook compose REF --url URL` and show the two lines it prints for `.storybook/main` if they are missing. After `npm run build-storybook`, run `openguildkit storybook import`, with `--company-index` and `--library` when the user provides them, and show the components to map and the conflicts. In a Design review, cite a recorded story as `storybook:STORY_ID`. Ask before downloading an index or installing a package.

When the user wants a design system from an existing application, run `openguildkit storybook extract` on the screens and folders they select, then `openguildkit storybook propose`. Show the proposals and the hypotheses, and record only the validations, rejections and names the user gives. Run `openguildkit storybook generate`, then `npm run build-storybook`, and report the files kept because the team changed them.
