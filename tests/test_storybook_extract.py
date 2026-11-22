import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openguildkit.cli import main
from openguildkit import storybook, storybook_cli
from openguildkit.storage import read_json, write_json
from openguildkit.storybook import PROPOSALS, generate, propose, validate_proposals
from openguildkit.storybook_extract import _strip_js_comments, extract, normalize_color

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "examples" / "storybook-extract"
EXAMPLE = REPO / "examples" / "request-status"


def by_key(items, field="key"):
    return {item[field]: item for item in items}


class ExtractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_the_example_app_gives_components_variants_and_tokens_tied_to_their_origin(self):
        inventory = extract(APP, [APP / "src"])
        components = by_key(inventory["components"], "name")
        self.assertEqual({key: components["Button"][key] for key in ("file", "line", "export", "usages", "confidence")},
                         {"file": "src/components/Button.tsx", "line": 12, "export": "named", "usages": 5,
                          "confidence": "observed"})
        self.assertTrue(components["Button"]["children"])
        self.assertEqual(components["StatusBadge"]["props"],
                         [{"name": "status", "options": ["open", "waiting", "closed"],
                           "required": True, "sample": "open"},
                          {"name": "label", "required": True, "sample": "Sample label"}])
        variants = by_key(inventory["variants"])
        self.assertEqual(variants['Button:variant="danger"']["confidence"], "hypothesis")
        self.assertEqual(variants['Button:variant="danger"']["origins"], ["src/pages/RequestDetail.tsx:9"])
        self.assertEqual((variants['Button:variant="primary"']["basis"], variants['Button:variant="primary"']["occurrences"]),
                         ("default", 2))
        self.assertEqual(variants["Button:disabled=true"]["props"], {"disabled": True})
        self.assertNotIn('StatusBadge:label="Open"', variants)
        tokens = by_key(inventory["tokens"])
        self.assertEqual((tokens["color:#0a66c2"]["name_hint"], tokens["color:#0a66c2"]["occurrences"]), ("color-brand", 5))
        self.assertEqual(tokens["color:#ffffff"]["occurrences"], 4)
        self.assertIn("color:#5f6b7a", tokens)
        self.assertEqual(tokens["radius:999px"]["confidence"], "hypothesis")
        self.assertEqual(tokens['font-family:"Inter", system-ui, sans-serif']["name_hint"], "font-body")
        self.assertEqual(inventory["external_components"], [])

    def test_component_and_usage_forms_are_recognized(self):
        source = self.root / "src"
        source.mkdir()
        (source / "Card.tsx").write_text(
            "import { forwardRef, memo, useState } from 'react';\n"
            "// export function Commented() { return <div/> }\n"
            "const Card = ({ tone = 'quiet', title }: Props) => <div>{title}</div>;\n"
            "export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field({ size }, ref) {\n"
            "  return <input ref={ref} />;\n"
            "});\n"
            "export const Tag = memo(({ kind }: { kind: string }) => <b>{kind}</b>);\n"
            "export default function Panel() {\n"
            "  const [items] = useState<Item[]>([]);\n"
            "  return <Card tone=\"loud\" title={`x`} onSelect={() => items.length > 1} {...rest}>\n"
            "    <Card.Header />\n"
            "  </Card>;\n"
            "}\n"
            "export const API_URL = 'https://example.com';\n"
            "export { Card as Tile };\n")
        (source / "Card.stories.tsx").write_text("export const Story = () => <Card tone=\"loud\" />;\n")
        inventory = extract(self.root, [source])
        components = by_key(inventory["components"], "name")
        self.assertEqual(sorted(components), ["Card", "Field", "Panel", "Tag"])
        self.assertEqual((components["Panel"]["export"], components["Card"]["export"]), ("default", "named"))
        self.assertEqual(components["Card"]["line"], 3)
        self.assertEqual(components["Field"]["props"], [{"name": "size"}])
        self.assertEqual(components["Card"]["usages"], 1)
        self.assertEqual(by_key(inventory["variants"])['Card:tone="loud"']["origins"], ["src/Card.tsx:10"])
        self.assertEqual(inventory["external_components"], [{"name": "Card.Header", "usages": 1}])
        self.assertEqual(_strip_js_comments("a // b\n/* c\nd */ e").count("\n"), 2)

    def test_colors_are_normalized_from_every_css_notation(self):
        self.assertEqual(normalize_color("#ABC"), "#aabbcc")
        self.assertEqual(normalize_color("#0a66c2ff"), "#0a66c2")
        self.assertEqual(normalize_color("rgb(10 102 194 / 50%)"), "#0a66c280")
        self.assertEqual(normalize_color("rgba(255, 0, 0, 0.5)"), "#ff000080")
        self.assertEqual(normalize_color("hsl(0, 100%, 50%)"), "#ff0000")
        self.assertIsNone(normalize_color("rgb(1, 2)"))


class ProposalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(APP / "src", self.root / "src")
        self.state = self.root / ".openguildkit"
        write_json(self.state / "storybook" / "inventory.json", extract(self.root, [self.root / "src"]))
        self.path = self.state / PROPOSALS

    def decide(self, statuses, names=None):
        data = read_json(self.path)
        for field in ("components", "variants", "tokens"):
            for item in data[field]:
                item["status"] = statuses.get(item["key"], item["status"])
                item["name"] = (names or {}).get(item["key"], item["name"])
        write_json(self.path, data)

    def test_propose_keeps_decisions_names_and_items_no_longer_observed(self):
        summary = propose(self.root, self.state)
        self.assertEqual(summary["kept"], 0)
        data = read_json(self.path)
        self.assertEqual(by_key(data["components"])["component:RequestList"]["kind"], "screen")
        self.assertEqual(by_key(data["components"])["component:StatusBadge"]["sample_args"],
                         {"label": "Sample label", "status": "open"})
        self.assertEqual(by_key(data["tokens"])["token:color:#0a66c2"]["name"], "color.brand")
        self.assertEqual(by_key(data["tokens"])["token:spacing:8px"]["name"], "spacing.2")
        self.decide({"component:Button": "validated", "token:color:#c62828": "rejected"},
                    {"token:color:#b26a00": "color.warning"})
        data = read_json(self.path)
        data["variants"].append({"key": "variant:Button:loading", "component": "component:Button", "name": "Loading",
                                 "props": {"disabled": True}, "status": "proposed", "basis": "preview",
                                 "confidence": "observed"})
        write_json(self.path, data)
        (self.root / "src" / "components" / "Button.css").unlink()
        write_json(self.state / "storybook" / "inventory.json", extract(self.root, [self.root / "src"]))
        summary = propose(self.root, self.state)
        data = read_json(self.path)
        self.assertEqual(by_key(data["components"])["component:Button"]["status"], "validated")
        tokens = by_key(data["tokens"])
        self.assertEqual(tokens["token:color:#b26a00"]["name"], "color.warning")
        self.assertEqual((tokens["token:color:#c62828"]["status"], tokens["token:color:#c62828"]["observed"]),
                         ("rejected", False))
        self.assertEqual(by_key(data["variants"])["variant:Button:loading"]["confidence"], "hypothesis")
        self.assertGreater(summary["not_observed"], 0)

    def test_invalid_decisions_are_refused(self):
        propose(self.root, self.state)
        data = read_json(self.path)
        data["tokens"][0]["status"] = "maybe"
        with self.assertRaisesRegex(ValueError, "proposed, validated or rejected"):
            validate_proposals(data)
        data = read_json(self.path)
        for item in data["tokens"][:2]:
            item.update(status="validated", name="color.same")
        with self.assertRaisesRegex(ValueError, "used twice"):
            validate_proposals(data)
        data = read_json(self.path)
        data["tokens"][0]["name"] = "color.{brand}"
        with self.assertRaisesRegex(ValueError, "braces"):
            validate_proposals(data)

    def test_generate_writes_validated_items_only_and_keeps_edited_files(self):
        propose(self.root, self.state)
        self.assertEqual(generate(self.root, self.state)["written"], [])
        self.decide({
            "component:StatusBadge": "validated", 'variant:StatusBadge:status="waiting"': "validated",
            'variant:StatusBadge:status="open"': "validated", 'variant:Button:variant="danger"': "validated",
            "token:color:#0a66c2": "validated", "token:spacing:8px": "validated", "token:radius:6px": "validated",
            'token:font-family:"Inter", system-ui, sans-serif': "validated", "token:color:#5f6b7a": "validated",
        })
        result = generate(self.root, self.state)
        out = self.root / "src" / "design-system"
        self.assertEqual(result["written"], ["src/design-system/StatusBadge.stories.tsx",
                                             "src/design-system/design.tokens.json", "src/design-system/index.ts"])
        self.assertEqual(result["skipped"], [{"key": 'variant:Button:variant="danger"',
                                              "reason": "its component is not validated"}])
        story = (out / "StatusBadge.stories.tsx").read_text()
        self.assertIn('import { StatusBadge } from "../components/StatusBadge";', story)
        self.assertIn('label: "Sample label"', story)
        self.assertNotIn("Waiting for you", story)
        self.assertLess(story.index("export const Open"), story.index("export const Waiting"))
        self.assertIn('"origins": ["src/pages/RequestList.tsx:15"], "confidence": "hypothesis"', story)
        self.assertIn('definition: "src/components/StatusBadge.tsx:5"', story)
        tokens = json.loads((out / "design.tokens.json").read_text())
        self.assertEqual(tokens["color"]["brand"]["$value"],
                         {"colorSpace": "srgb", "components": [0.0392, 0.4, 0.7608], "hex": "#0a66c2"})
        self.assertEqual(tokens["spacing"]["2"]["$value"], {"value": 8, "unit": "px"})
        self.assertEqual(tokens["font-family"]["body"]["$type"], "fontFamily")
        self.assertEqual(tokens["font-family"]["body"]["$value"], ["Inter", "system-ui", "sans-serif"])
        self.assertEqual((out / "index.ts").read_text().splitlines()[1],
                         'export { StatusBadge } from "../components/StatusBadge";')

        edited = story + "export const Empty: Story = { args: { label: '' } };\n"
        (out / "StatusBadge.stories.tsx").write_text(edited)
        self.decide({"token:radius:999px": "validated"})
        again = generate(self.root, self.state)
        self.assertEqual(again["kept"], ["src/design-system/StatusBadge.stories.tsx"])
        self.assertEqual(again["written"], ["src/design-system/design.tokens.json"])
        self.assertEqual((out / "StatusBadge.stories.tsx").read_text(), edited)
        self.decide({"component:StatusBadge": "rejected"})
        self.assertIn("src/design-system/StatusBadge.stories.tsx", generate(self.root, self.state)["left"])
        with self.assertRaisesRegex(ValueError, "inside the project"):
            generate(self.root, self.state, out=self.root.parent / "elsewhere")

    def test_the_cli_runs_the_whole_extraction(self):
        def cli(*args, code=0):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(["--project", str(self.root), *map(str, args)]), code, err.getvalue())
            return out.getvalue()

        write_json(self.root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text()))
        cli("init", "--answers", self.root / "profile.json")
        screenshot = self.root / "list.png"
        screenshot.write_bytes(b"\x89PNG synthetic")
        inventory = json.loads(cli("storybook", "extract", "--src", self.root / "src" / "pages",
                                   "--src", self.root / "src" / "components", "--preview", screenshot, "--json"))
        self.assertEqual(inventory["previews"][0]["path"], "list.png")
        self.assertIn("hypotheses", cli("storybook", "propose"))
        self.decide({"component:Button": "validated", 'variant:Button:variant="secondary"': "validated"})
        generated = cli("storybook", "generate")
        self.assertIn("Written: src/design-system/Button.stories.tsx", generated)
        self.assertIn("Missing Storybook dependencies in package.json: @storybook/react-vite, storybook", generated)
        self.assertIn("Missing Storybook configuration (.storybook/main.ts or .storybook/main.js)", generated)
        warnings = json.loads(cli("storybook", "generate", "--json"))["warnings"]
        self.assertIn("Missing Storybook configuration (.storybook/main.ts or .storybook/main.js).", warnings)
        write_files(self.root, {".storybook/main.ts": "export default {};"})
        write_json(self.root / "package.json", {"devDependencies": {"@storybook/react-vite": "^10", "storybook": "^10"}})
        self.assertNotIn("warnings", json.loads(cli("storybook", "generate", "--json")))
        self.assertIn("Unchanged: src/design-system/Button.stories.tsx", cli("storybook", "generate"))

    def test_two_css_variables_with_the_same_value_keep_their_names(self):
        (self.root / "src" / "styles" / "theme.css").write_text(
            ":root { --space-4: 4px; --spacing-4: 4px; --space-panel: 8px; }", encoding="utf-8")
        write_json(self.state / storybook.INVENTORY, extract(self.root, [self.root / "src"]))
        propose(self.root, self.state)
        data = by_key(read_json(self.path)["tokens"])
        self.assertEqual(data["token:spacing:4px"]["name"], "spacing.space-4")
        self.assertEqual(data["token:spacing:4px:--spacing-4"]["name"], "spacing.spacing-4")
        self.assertEqual(data["token:spacing:8px"]["name"], "spacing.panel")



def write_files(base, files):
    for name, text in files.items():
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def validate_all(state, keys):
    data = read_json(state / PROPOSALS)
    for field in ("components", "variants", "tokens"):
        for item in data[field]:
            if item["key"] in keys or (field == "variants" and item["component"] in keys):
                item["status"] = "validated"
    write_json(state / PROPOSALS, data)


def exported_names(source: str) -> set:
    """The names a module exports, read the way a bundler would for these small synthetic files."""
    names = set(re.findall(r"export\s+(?:const|function)\s+(\w+)", source))
    if re.search(r"export\s+default\b", source):
        names.add("default")
    for listed in re.findall(r"export\s*\{([^}]*)\}", source):
        names.update(item.split(" as ")[-1].strip() for item in listed.split(",") if item.strip())
    return names


class GeneratedCodeTests(unittest.TestCase):
    """Generated stories and index import names that exist; nothing generated holds an absolute path."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def assert_imports_exist(self, out, text):
        """Every import or re-export in a generated file names something its target module exports."""
        statements = re.findall(r'(?:import|export)\s+(\{[^}]*\}|\w+)\s+from\s+"([^"]+)"', text)
        self.assertTrue(statements)
        for clause, target in statements:
            if target.startswith("@storybook/"):
                continue
            source = next((out / (target + suffix)).resolve() for suffix in (".tsx", ".jsx")
                          if (out / (target + suffix)).exists())
            exports = exported_names(source.read_text(encoding="utf-8"))
            wanted = ["default"] if not clause.startswith("{") else [
                item.split(" as ")[0].strip() for item in clause.strip("{} ").split(",")]
            for name in wanted:
                self.assertIn(name, exports, f"{clause} from {target}")

    def test_a_component_exported_under_another_name_is_imported_by_that_name(self):
        write_files(self.root / "src", {
            "components/Card.tsx": "function Card({ title, elevated = false }) { return <div>{title}</div>; }\n"
                                   "export { Card as Panel };\n",
            "components/Tile.tsx": "export function Tile({ tone = 'quiet' }) { return <b>{tone}</b>; }\n",
            "components/Shelf.tsx": "const Shelf = ({ dense = false }) => <ul />;\nexport default Shelf;\n",
            "components/Both.tsx": "function Both({ open = false }) { return <i/>; }\nexport { Both, Both as Twin };\n",
            "components/index.ts": "export { Tile as Badge } from './Tile';\n"
                                   "export { default as Rack } from './Shelf';\n",
            "pages/Home.tsx": "import { Panel } from '../components/Card';\n"
                              "import { Badge, Rack } from '../components';\n"
                              "export function Home() {\n"
                              "  return <main><Panel title=\"x\" elevated /><Badge tone=\"loud\" /><Rack dense />"
                              "<Twin open /><Both /></main>;\n}\n",
        })
        inventory = extract(self.root, [self.root / "src"])
        components = by_key(inventory["components"], "name")
        self.assertEqual({name: components[name]["usages"] for name in ("Card", "Tile", "Shelf", "Both")},
                         {"Card": 1, "Tile": 1, "Shelf": 1, "Both": 2})
        self.assertEqual((components["Card"]["export"], components["Card"]["public"]), ("named", "Panel"))
        self.assertNotIn("public", components["Both"])
        self.assertEqual(inventory["external_components"], [])
        variants = by_key(inventory["variants"])
        for key in ("Card:elevated=true", 'Tile:tone="loud"', "Shelf:dense=true", "Both:open=true"):
            self.assertIn(key, variants)
        self.assertEqual(variants["Card:elevated=true"]["origins"], ["src/pages/Home.tsx:4"])

        state = self.root / ".openguildkit"
        write_json(state / "storybook" / "inventory.json", inventory)
        propose(self.root, state)
        validate_all(state, {"component:Card", "component:Tile", "component:Shelf", "component:Both"})
        generate(self.root, state)
        out = self.root / "src" / "design-system"
        card = (out / "Card.stories.tsx").read_text(encoding="utf-8")
        self.assertIn('import { Panel as Card } from "../components/Card";', card)
        self.assertIn("component: Card,", card)
        self.assertIn("elevated: true", card)
        index = (out / "index.ts").read_text(encoding="utf-8")
        self.assertIn('export { Panel as Card } from "../components/Card";', index)
        self.assertIn('export { default as Shelf } from "../components/Shelf";', index)
        self.assertIn('export { Tile } from "../components/Tile";', index)
        self.assertIn('export { Both } from "../components/Both";', index)
        for path in sorted(out.glob("*.ts*")):
            with self.subTest(file=path.name):
                self.assert_imports_exist(out, path.read_text(encoding="utf-8"))

    def test_a_public_name_that_is_not_an_identifier_is_refused(self):
        data = {"schema_version": 1, "variants": [], "tokens": [], "components": [
            {"key": "component:Card", "name": "Card", "status": "validated", "file": "src/Card.tsx", "line": 1,
             "export": "named", "public": "Panel } from 'x'; //"}]}
        with self.assertRaisesRegex(ValueError, "public"):
            validate_proposals(data)

    def test_typed_string_unions_give_their_variants_without_any_usage(self):
        write_files(self.root / "src", {
            "Button.tsx": 'type Variant = "primary" | "ghost";\n'
                          'export function Button({ variant = "primary", label }: '
                          '{ variant?: Variant; label: string }) {\n'
                          "  return <button className={variant}>{label}</button>;\n}\n",
            "Chip.tsx": "type Size = 'sm' | 'lg';\n"
                        "interface ChipProps {\n  tone?: 'info' | 'warn';\n  size?: Size;\n"
                        "  type?: 'button' | 'submit';\n}\n"
                        "export const Chip = ({ tone = 'info', size, type }: ChipProps) => <i>{tone}</i>;\n",
            "Tag.tsx": "import type { FC } from 'react';\n"
                       "export type TagProps = { kind?: 'new' | 'old' };\n"
                       "export const Tag: FC<TagProps> = ({ kind = 'new' }) => <b>{kind}</b>;\n",
        })
        inventory = extract(self.root, [self.root / "src"])
        components = by_key(inventory["components"], "name")
        self.assertEqual(components["Button"]["props"][0], {"name": "variant", "default": "primary",
                                                            "options": ["primary", "ghost"]})
        variants = by_key(inventory["variants"])
        self.assertEqual(sorted(key for key in variants if key.startswith("Button")),
                         ['Button:variant="ghost"', 'Button:variant="primary"'])
        self.assertEqual(variants['Button:variant="ghost"']["basis"], "type")
        self.assertEqual(variants['Button:variant="primary"']["basis"], "default")
        self.assertEqual(variants['Button:variant="ghost"']["origins"], ["src/Button.tsx:2"])
        self.assertEqual(variants['Button:variant="ghost"']["confidence"], "hypothesis")
        for key in ('Chip:tone="info"', 'Chip:tone="warn"', 'Chip:size="sm"', 'Chip:size="lg"', 'Chip:type="submit"',
                    'Tag:kind="new"', 'Tag:kind="old"'):
            self.assertIn(key, variants)
        self.assertIn("4 variants", "\n".join(storybook_cli._print_extract(
            {**inventory, "variants": inventory["variants"][:4]}, "inventory.json")))

    def test_required_props_and_validated_states_generate_typed_args(self):
        write_files(self.root / "src", {
            "PriceTag.tsx": 'export function PriceTag({ amount, currency }: '
                            '{ amount: number; currency: "EUR" | "USD"; minorUnits: boolean }) {\n'
                            "  return <span>{amount} {currency}</span>;\n}\n",
            "Button.tsx": 'export function Button({ label, type }: { label: string; type?: "button" | "submit" }) {\n'
                          "  return <button type={type}>{label}</button>;\n}\n",
            "ProductCard.tsx": "type Product = { name: string; stocked: boolean; tags: string[] };\n"
                               "export function ProductCard({ product, soldOut }: "
                               "{ product: Product; soldOut: boolean }) {\n"
                               "  return <div>{soldOut ? 'Sold out' : product.name}</div>;\n}\n",
            "App.tsx": "export function App() {\n"
                       '  return <ProductCard product={{ name: "Private title", stocked: false, tags: [] }} soldOut />;\n'
                       "}\n",
        })
        state = self.root / ".openguildkit"
        write_json(state / storybook.INVENTORY, extract(self.root, [self.root / "src"]))
        propose(self.root, state)
        validate_all(state, {"component:Button", "component:PriceTag", "component:ProductCard"})
        generate(self.root, state)
        out = self.root / "src" / "design-system"
        price = (out / "PriceTag.stories.tsx").read_text(encoding="utf-8")
        self.assertIn("amount: 1", price)
        self.assertIn("minorUnits: false", price)
        self.assertIn('currency: "EUR"', price)
        self.assertIn('currency: "USD"', price)
        self.assertIn("type Story = StoryObj<typeof meta>;", price)
        button = (out / "Button.stories.tsx").read_text(encoding="utf-8")
        self.assertIn('label: "Sample label"', button)
        self.assertIn('type: "submit"', button)
        self.assertNotIn("export const Button:", button)
        product = (out / "ProductCard.stories.tsx").read_text(encoding="utf-8")
        self.assertIn('product: {"name": "Sample name", "stocked": false, "tags": []}', product)
        self.assertIn("soldOut: true", product)
        self.assertNotIn("Private title", product)

    def test_boolean_states_callbacks_and_the_detected_framework_reach_the_stories(self):
        write_files(self.root / "src", {
            "ProductCard.tsx": "interface ProductCardProps {\n  name: string;\n  inStock?: boolean;\n"
                               "  onNotify: (input: { email: string }) => void;\n}\n"
                               "export function ProductCard({ name, inStock = true, onNotify }: ProductCardProps) {\n"
                               "  return <article>{name}</article>;\n}\n",
            "Button.tsx": "export function Button({ label, disabled = false }: { label: string; disabled?: boolean }) {\n"
                          "  return <button disabled={disabled}>{label}</button>;\n}\n",
        })
        write_json(self.root / "package.json", {"dependencies": {"next": "15.0.0", "react": "19.0.0"},
                                                "devDependencies": {"storybook": "8.4.0"}})
        state = self.root / ".openguildkit"
        write_json(state / storybook.INVENTORY, extract(self.root, [self.root / "src"]))
        propose(self.root, state)
        variants = by_key(read_json(state / PROPOSALS)["variants"])
        self.assertEqual(variants["variant:ProductCard:inStock=false"]["name"], "Not In Stock")
        self.assertEqual(variants["variant:ProductCard:inStock=false"]["confidence"], "hypothesis")
        self.assertEqual(variants["variant:Button:disabled=true"]["name"], "Disabled")
        validate_all(state, {"component:ProductCard", "component:Button"})
        result = generate(self.root, state)
        self.assertEqual(result["framework"], "@storybook/nextjs-vite")
        self.assertEqual(result["warnings"][0], "Missing Storybook dependencies in package.json: @storybook/nextjs-vite.")
        self.assertFalse(any("onNotify" in warning for warning in result["warnings"]))
        out = self.root / "src" / "design-system"
        card = (out / "ProductCard.stories.tsx").read_text(encoding="utf-8")
        self.assertIn('import type { Meta, StoryObj } from "@storybook/nextjs-vite";', card)
        self.assertIn("    onNotify: () => {},", card)
        self.assertIn("export const NotInStock: Story", card)
        self.assertIn("inStock: false", card)
        self.assertIn("disabled: true", (out / "Button.stories.tsx").read_text(encoding="utf-8"))
        self.assertFalse((self.root / "node_modules").exists())
        write_json(self.root / "package.json", {"devDependencies": {"@storybook/react-webpack5": "8.4.0", "storybook": "8.4.0"}})
        self.assertEqual(storybook.detect_framework(self.root), "@storybook/react-webpack5")
        self.assertEqual(generate(self.root, state, framework="@storybook/react-vite")["framework"], "@storybook/react-vite")

    def test_a_state_named_like_its_component_is_its_default_story(self):
        write_files(self.root / "src", {
            "Button.tsx": 'export function Button({ label, type = "button" }: { label: string; type?: "button" | "submit" }) {\n'
                          "  return <button type={type}>{label}</button>;\n}\n",
            "Page.tsx": 'export function Page() { return <Button label="Go" />; }\n',
        })
        state = self.root / ".openguildkit"
        write_json(state / storybook.INVENTORY, extract(self.root, [self.root / "src"]))
        propose(self.root, state)
        variants = by_key(read_json(state / PROPOSALS)["variants"])
        self.assertEqual(variants['variant:Button:type="button"']["name"], "Default")
        self.assertEqual(variants['variant:Button:type="submit"']["name"], "Submit")
        data = read_json(state / PROPOSALS)
        by_key(data["variants"])['variant:Button:type="button"']["name"] = "Button"
        write_json(state / PROPOSALS, data)
        validate_all(state, {"component:Button"})
        generate(self.root, state)
        story = (self.root / "src" / "design-system" / "Button.stories.tsx").read_text(encoding="utf-8")
        self.assertIn("export const Default: Story", story)
        self.assertIn('  name: "Default",', story)
        self.assertIn("export const Submit: Story", story)
        self.assertNotIn("Button2", story)

    def test_token_names_drop_the_kind_their_variable_repeats_the_same_way_on_every_run(self):
        write_files(self.root / "src", {"theme.css": (
            ":root { --color-brand: #0a66c2; --clr-alert: #c62828; --brand-ink: #1f2933; --space-4: 16px; "
            "--radius-md: 6px; --font-size-sm: 0.875rem; --font-body: Inter, sans-serif; }\n"
            ".a { color: var(--color-brand); padding: var(--space-4); margin: 3px; }\n")})
        state = self.root / ".openguildkit"
        names = []
        for _ in range(2):
            write_json(state / storybook.INVENTORY, extract(self.root, [self.root / "src"]))
            propose(self.root, state)
            names.append({item["key"]: item["name"] for item in read_json(state / PROPOSALS)["tokens"]})
        self.assertEqual(names[0], names[1])
        self.assertEqual(sorted(names[0].values()), [
            "color.alert", "color.brand", "color.brand-ink", "font-family.body", "font-size.sm", "radius.md",
            "spacing.3px", "spacing.4"])
        hypotheses = [item for item in read_json(state / PROPOSALS)["tokens"] if item["confidence"] == "hypothesis"]
        self.assertTrue(hypotheses)

    def test_a_source_outside_the_project_leaves_no_absolute_path_in_what_is_generated(self):
        project, other = self.root / "project", self.root / "other-app"
        write_files(other / "src", {
            "Button.tsx": "export function Button({ tone = 'calm' }) { return <button>{tone}</button>; }\n",
            "Page.tsx": "export function Page() { return <Button tone=\"loud\" />; }\n",
            "theme.css": ":root { --color-brand: #0a66c2; }\n.a { color: var(--color-brand); }\n",
        })
        project.mkdir()
        state = project / ".openguildkit"
        inventory = extract(project, [other / "src"])
        self.assertEqual(inventory["sources"], ["../other-app/src"])
        self.assertEqual(by_key(inventory["components"], "name")["Button"]["file"], "../other-app/src/Button.tsx")
        write_json(state / "storybook" / "inventory.json", inventory)
        propose(project, state)
        validate_all(state, {"component:Button", "token:color:#0a66c2"})
        result = generate(project, state)
        self.assertIn("src/design-system/Button.stories.tsx", result["written"])
        story = (project / "src" / "design-system" / "Button.stories.tsx").read_text(encoding="utf-8")
        self.assertIn('definition: "../other-app/src/Button.tsx:1"', story)
        self.assertIn('from "../../../other-app/src/Button";', story)
        self.assert_imports_exist(project / "src" / "design-system", story)
        for path in [*project.rglob("*.json"), *project.rglob("*.ts*")]:
            with self.subTest(file=path.name):
                self.assertNotIn(self.root.as_posix(), path.read_text(encoding="utf-8"))

    def test_a_source_whose_relative_path_would_name_the_home_folder_is_recorded_by_base_name(self):
        project, home = self.root / "work" / "project", self.root / "home" / "someone"
        write_files(home / "app" / "src", {
            "Button.tsx": "export function Button({ tone = 'calm' }) { return <button>{tone}</button>; }\n"})
        project.mkdir(parents=True)
        state = project / ".openguildkit"
        with mock.patch.object(storybook, "_home", return_value=home):
            inventory = extract(project, [home / "app" / "src"])
            write_json(state / "storybook" / "inventory.json", inventory)
            propose(project, state)
            validate_all(state, {"component:Button"})
            result = generate(project, state)
        self.assertEqual(inventory["sources"], ["outside:src"])
        self.assertEqual(by_key(inventory["components"], "name")["Button"]["file"], "outside:src/Button.tsx")
        self.assertIn("outside the project", " ".join(inventory["notes"]))
        self.assertEqual(result["written"], [])
        self.assertIn("outside the project", result["skipped"][0]["reason"])
        for path in project.rglob("*.json"):
            self.assertNotIn("someone", path.read_text(encoding="utf-8"))

    def test_extract_help_names_what_is_supported_and_what_is_not(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exit_:
            main(["storybook", "extract", "--help"])
        self.assertEqual(exit_.exception.code, 0)
        text = " ".join(out.getvalue().split())
        for words in ("React function components", "CSS and SCSS", "class components", "CSS-in-JS", "Tailwind",
                      "Vue, Angular and Svelte"):
            self.assertIn(words, text)

if __name__ == "__main__":
    unittest.main()
