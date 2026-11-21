"""Export the OGK character sources as pixel sprites, portraits and room miniatures."""

import json
from math import pi, sin
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat


@dataclass(frozen=True)
class Character:
    key: str
    name: str
    height: int
    face_x: float = 0.5
    face_crop: float = 0.53
    avatar_top: float = 0.040
    avatar_crop: float = 0.38
    avatar_light: int = 0


CAST = {
    "01-atelier": (
        Character("product", "Stratège", 103, 0.46),
        Character("engineering", "Bâtisseur", 104, 0.54),
        Character("architecture", "Cartographe", 104, 0.48),
        Character("documentation", "Scribe", 100, 0.48),
    ),
    "02-revue": (
        Character("design", "Artisan", 101, 0.52, 0.56),
        Character("security", "Gardien", 106, 0.50),
        Character("privacy", "Magistrat", 104, 0.54),
        Character("quality", "Inspecteur", 101, 0.53),
    ),
    "03-systemes": (
        Character("performance", "Alchimiste", 105, 0.57, avatar_top=0.10, avatar_crop=0.31),
        Character("data", "Savant", 102, 0.56),
        Character("platform", "Maître des forges", 102, 0.61),
        Character("market", "Éclaireur", 98),
    ),
    "04-alliance": (
        Character("marketing", "Barde", 102, 0.54),
        Character("commerce", "Négociant", 103, 0.53),
        Character("human-1", "Camille Roche", 103),
        Character("human-2", "Yanis Belkacem", 104, 0.46),
    ),
    "05-intendance": (
        Character("human-3", "Inès Morel", 101, 0.44, avatar_top=0.115, avatar_crop=0.31, avatar_light=33),
        Character("human-4", "Théo Garnier", 103, 0.5, 0.50),
        Character("human-5", "Léa Fontaine", 101, 0.47),
        Character("human-6", "Hugo Martin", 104, 0.56, 0.51),
    ),
}

INK = (2, 5, 8)
MINT = (110, 247, 196)
WHITE = (253, 253, 253)
GLYPHS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def mix(start, finish, weight):
    return tuple(round(a + (b - a) * weight) for a, b in zip(start, finish))


def palette():
    colors = [INK]
    for tone, stops in (
        (WHITE, (0.035, 0.065, 0.100, 0.158, 0.220, 0.285, 0.355, 0.425, 0.500, 0.580,
                 0.660, 0.740, 0.820, 0.900, 0.965, 1)),
        (MINT, (0.055, 0.091, 0.145, 0.200, 0.265, 0.345, 0.445, 0.555, 0.680, 0.810, 1)),
    ):
        colors.extend(mix(INK, tone, stop) for stop in stops)
    colors.extend(mix(MINT, WHITE, stop) for stop in (0.24, 0.45, 0.65, 0.82))
    return colors


def crop_figures(atlas):
    """Find the transparent gutter nearest each nominal column boundary."""
    alpha = atlas.getchannel("A").point(lambda value: 255 if value > 127 else 0)
    bounds = [0]
    for i in range(1, 4):
        center = atlas.width * i // 4
        drift = atlas.width // 12
        bounds.append(min(
            range(center - drift, center + drift),
            key=lambda x: (ImageStat.Stat(alpha.crop((x, 0, x + 1, atlas.height))).sum[0],
                           abs(x - center)),
        ))
    bounds.append(atlas.width)
    for left, right in zip(bounds, bounds[1:]):
        tile = atlas.crop((left, 0, right, atlas.height))
        extent = alpha.crop((left, 0, right, atlas.height)).getbbox()
        if extent is None:
            raise ValueError("Empty character slot in the atlas")
        yield tile.crop(extent)


def figure_grid(image, width, height, body_height, foot_margin):
    scale = min((width - 4) / image.width, body_height / image.height)
    result = image.resize((round(image.width * scale), round(image.height * scale)),
                          Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height))
    canvas.paste(result, ((width - result.width) // 2, height - foot_margin - result.height))
    return canvas


def portrait_grid(image, cast, size):
    small = size < 64
    span = round(image.height * (cast.avatar_crop if small else cast.face_crop))
    left = round(image.width * cast.face_x) - span // 2
    top = round(image.height * (cast.avatar_top if small else -0.025))
    crop = image.crop((left, top, left + span, top + span)).resize((size, size), Image.Resampling.LANCZOS)
    if small and cast.avatar_light:
        midtones = [round(value + cast.avatar_light * sin(pi * value / 255)) for value in range(256)]
        lightened = crop.convert("RGB").point(midtones * 3)
        lightened.putalpha(crop.getchannel("A"))
        return lightened
    return crop


def indexed(image, colors):
    table = Image.new("P", (1, 1))
    table.putpalette([component for color in (colors + [INK] * (256 - len(colors)))
                      for component in color])
    result = image.convert("RGB").quantize(palette=table, dither=Image.Dither.NONE).convert("RGBA")
    result.putalpha(image.getchannel("A").point(lambda value: 255 if value > 127 else 0))
    return result


def glyph_rows(image, color_glyphs):
    rows = []
    for y in range(image.height):
        row = []
        for x in range(image.width):
            r, g, b, alpha = image.getpixel((x, y))
            row.append(color_glyphs[(r, g, b)] if alpha else ".")
        rows.append("".join(row))
    return rows


def label_font():
    for face in ("segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(face, 13)
        except OSError:
            continue
    return ImageFont.load_default(size=13)


def preview_entry(canvas, index, character, figure, portrait, avatar, font):
    x, y = 216 * (index % 5), 159 * (index // 5)
    drawing = ImageDraw.Draw(canvas)
    drawing.rectangle((x + 5, y + 5, x + 210, y + 151), fill="#102120", outline="#34534d")
    drawing.rectangle((x + 107, y + 19, x + 186, y + 98), fill="#192d2d")
    drawing.rectangle((x + 132, y + 103, x + 159, y + 130), fill="#192d2d")
    canvas.alpha_composite(figure, (x + 17, y + 9))
    canvas.alpha_composite(portrait.resize((80, 80), Image.Resampling.NEAREST), (x + 107, y + 19))
    canvas.alpha_composite(avatar.resize((28, 28), Image.Resampling.NEAREST), (x + 132, y + 103))
    drawing.text((x + 108, y + 138), character.name, anchor="mm", fill="#fdfdfd",
                 font=font)


def main():
    web = Path(__file__).resolve().parents[1]
    source = web / "docs/art/personnages"
    destination = web / "public/assets/characters"
    destination.mkdir(parents=True, exist_ok=True)
    colors = palette()
    glyphs = {color: glyph for color, glyph in zip(colors, GLYPHS)}
    miniatures = {}
    sheet = Image.new("RGBA", (1080, 636), "#020508")
    font = label_font()
    for row, (atlas_name, subjects) in enumerate(CAST.items()):
        with Image.open(source / f"{atlas_name}.png") as atlas:
            for column, (cast, fragment) in enumerate(zip(subjects, crop_figures(atlas.convert("RGBA")), strict=True)):
                figure = indexed(figure_grid(fragment, 80, 112, cast.height, 3), colors)
                portrait = indexed(portrait_grid(fragment, cast, 96), colors)
                avatar = indexed(portrait_grid(fragment, cast, 40), colors)
                small = indexed(figure_grid(fragment, 16, 24, 22, 1), colors)
                miniatures[cast.key] = glyph_rows(small, glyphs)
                figure.save(destination / f"{cast.key}-figure.webp", lossless=True, method=6)
                portrait.save(destination / f"{cast.key}-portrait.webp", lossless=True, method=6)
                avatar.save(destination / f"{cast.key}-avatar.webp", lossless=True, method=6)
                preview_entry(sheet, row * 4 + column, cast, figure, portrait, avatar, font)

    manifest = {"palette": {g: "#%02x%02x%02x" % c for c, g in glyphs.items()},
                "rows": miniatures}
    output = web / "src/shared/pixel/character-miniatures.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sheet.convert("RGB").save(source / "planche.png", optimize=True)


if __name__ == "__main__":
    main()
