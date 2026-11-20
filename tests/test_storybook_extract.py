import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main
from openguildkit.storage import read_json, write_json
from openguildkit.storybook import (
    PROPOSALS, _strip_js_comments, extract, generate, normalize_color, propose, validate_proposals,
)

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
        self.assertEqual(components["StatusBadge"]["props"], [{"name": "status"}, {"name": "label"}])
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
        self.assertEqual(by_key(data["components"])["component:StatusBadge"]["text_props"], ["label"])
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
        self.assertEqual(tokens["font-family"]["body"], {**tokens["font-family"]["body"], "$type": "fontFamily",
                                                         "$value": ["Inter", "system-ui", "sans-serif"]})
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
        self.assertIn("Written: src/design-system/Button.stories.tsx", cli("storybook", "generate"))
        self.assertIn("Unchanged: src/design-system/Button.stories.tsx", cli("storybook", "generate"))


if __name__ == "__main__":
    unittest.main()
