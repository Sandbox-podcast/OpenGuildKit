import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

// The product (src/project, src/shared) must not reach into the demo: what the build of the product leaves out.
// The files that do today are counted in style-baseline.json (npm run lint); a new import fails.
const DEMO = ['@/domain', '@/domain/*', '@/adapters/*', '@/features/*', '@/fixtures/*', '@/app/*'].map((group) => ({
  group: [group],
  message: 'The demo is not in the package: the product must not import it (#500).',
}));

export default tseslint.config(
  { ignores: ['node_modules', 'dist', 'dist-demo', 'test-results', 'playwright-report', 'public', 'docs', 'data'] },
  ...tseslint.configs.recommended,
  { files: ['**/*.{ts,tsx,mjs}'], rules: { eqeqeq: ['error', 'always', { null: 'ignore' }] } },
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: { 'react-hooks/rules-of-hooks': 'error', 'react-hooks/exhaustive-deps': 'warn' },
  },
  {
    files: ['src/project/**/*.{ts,tsx}', 'src/shared/**/*.{ts,tsx}'],
    rules: { 'no-restricted-imports': ['error', { patterns: DEMO }] },
  },
);
