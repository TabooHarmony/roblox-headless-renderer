#!/usr/bin/env python3
"""Write the example models in examples/ (made for this repository, free to reuse).

    python scripts/make_examples.py

examples/shop.rbxmx    a shop ScreenGui: layouts, gradients, strokes, rounded corners,
                       text, and one deliberate mistake for `rhr check` to find
examples/tower.rbxmx   a small 3D build on a Baseplate with materials, lighting,
                       a SurfaceGui sign and a BillboardGui name tag
"""

from __future__ import annotations

from itertools import count
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "examples"
_ids = count()

BOLD = ("rbxasset://fonts/families/GothamSSm.json", 700)
MEDIUM = ("rbxasset://fonts/families/GothamSSm.json", 500)
BLACK = ("rbxasset://fonts/families/GothamSSm.json", 900)


# --- tiny rbxmx writer -------------------------------------------------------------

def udim2(xs, xo, ys, yo):
    return ("UDim2", f"<XS>{xs}</XS><XO>{xo}</XO><YS>{ys}</YS><YO>{yo}</YO>")


def udim(s, o):
    return ("UDim", f"<S>{s}</S><O>{o}</O>")


def vec2(x, y):
    return ("Vector2", f"<X>{x}</X><Y>{y}</Y>")


def vec3(x, y, z):
    return ("Vector3", f"<X>{x}</X><Y>{y}</Y><Z>{z}</Z>")


def rgb(hex_color: str):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return ("Color3", f"<R>{r:.4f}</R><G>{g:.4f}</G><B>{b:.4f}</B>")


def seq(*stops):
    """ColorSequence from (time, "#rrggbb") stops."""
    parts = []
    for t, hex_color in stops:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        parts.append(f"{t} {r:.4f} {g:.4f} {b:.4f} 0")
    return ("ColorSequence", " ".join(parts))


def font(face):
    family, weight = face
    return ("Font", f"<Family><url>{family}</url></Family><Weight>{weight}</Weight><Style>Normal</Style>")


def cframe(x, y, z, yaw_deg: float = 0.0):
    import math

    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    m = (c, 0, s, 0, 1, 0, -s, 0, c)
    rot = "".join(f"<R{i // 3}{i % 3}>{v:.6f}</R{i // 3}{i % 3}>" for i, v in enumerate(m))
    return ("CoordinateFrame", f"<X>{x}</X><Y>{y}</Y><Z>{z}</Z>{rot}")


def value(v):
    if isinstance(v, tuple):
        return v
    if isinstance(v, bool):
        return ("bool", "true" if v else "false")
    if isinstance(v, int):
        return ("int", str(v))
    if isinstance(v, float):
        return ("float", repr(v))
    return ("string", escape(str(v)))


def token(n: int):
    return ("token", str(n))


class I:
    """One instance: class, properties, children."""

    def __init__(self, cls: str, name: str, *children: "I", **props):
        self.cls, self.name, self.children, self.props = cls, name, list(children), props

    def xml(self, depth: int = 1) -> str:
        pad = "  " * depth
        lines = [f'{pad}<Item class="{self.cls}" referent="RBX{next(_ids)}">', f"{pad}  <Properties>",
                 f'{pad}    <string name="Name">{escape(self.name)}</string>']
        for key, raw in self.props.items():
            kind, text = value(raw)
            lines.append(f'{pad}    <{kind} name="{key}">{text}</{kind}>')
        lines.append(f"{pad}  </Properties>")
        lines += [child.xml(depth + 1) for child in self.children]
        lines.append(f"{pad}</Item>")
        return "\n".join(lines)


def write(path: Path, *roots: I) -> None:
    body = "\n".join(root.xml() for root in roots)
    path.write_text(f'<roblox version="4">\n{body}\n</roblox>\n', encoding="utf-8", newline="\n")
    print(path)


def corner(px: int | float, scale: float = 0) -> I:
    return I("UICorner", "UICorner", CornerRadius=udim(scale, px))


def stroke(color: str, thickness: float, *, border: bool = False, transparency: float = 0.0) -> I:
    return I("UIStroke", "UIStroke", Color=rgb(color), Thickness=float(thickness),
             ApplyStrokeMode=token(1 if border else 0), Transparency=float(transparency))


def label(name: str, text: str, face, size: int, color: str, pos, dims, *children, align: int = 2,
          **props) -> I:
    return I("TextLabel", name, *children, Text=text, FontFace=font(face), TextSize=float(size),
             TextColor3=rgb(color), BackgroundTransparency=1.0, Position=udim2(*pos), Size=udim2(*dims),
             TextXAlignment=token(align), **props)


# --- the shop UI -------------------------------------------------------------------

ITEMS = [
    # name, rarity, rarity colour, card gradient, price
    ("Starlight Blade", "LEGENDARY", "#ffcf4d", ("#5b3a0f", "#2a1b08"), "2,400"),
    ("Frost Bow", "EPIC", "#c77dff", ("#3d1f5c", "#1d1030"), "1,150"),
    ("Iron Shield", "RARE", "#4dabff", ("#16385c", "#0c1c30"), "480"),
    ("Healing Potion", "COMMON", "#b8c2cc", ("#2c333b", "#181c21"), "60"),
    # Deliberate mistake: the name is far too long for its label, so `rhr check`
    # reports it as text that cannot fit.
    ("Enchanted Dragonscale Greatsword of the Northern Wastes", "MYTHIC", "#ff5c7a",
     ("#5c1626", "#2e0b13"), "9,999"),
    ("Speed Boots", "RARE", "#4dabff", ("#16385c", "#0c1c30"), "520"),
]


def item_card(i: int, name: str, rarity: str, rarity_color: str, grad, price: str) -> I:
    return I(
        "Frame", f"Item{i + 1}",
        corner(12),
        stroke(rarity_color, 2, border=True, transparency=0.35),
        I("UIGradient", "UIGradient", Color=seq((0, grad[0]), (1, grad[1])), Rotation=90.0),
        # item "icon": a rounded tile with a glow
        I("Frame", "Icon",
          corner(10),
          I("UIGradient", "UIGradient", Color=seq((0, rarity_color), (1, grad[1])), Rotation=135.0),
          label("Glyph", name[0], BLACK, 34, "#ffffff", (0, 0, 0, 0), (1, 0, 1, 0)),
          Position=udim2(0.5, 0, 0, 14), AnchorPoint=vec2(0.5, 0), Size=udim2(0, 64, 0, 64),
          BorderSizePixel=token(0)),
        label("Rarity", rarity, BOLD, 11, rarity_color, (0, 0, 0, 86), (1, 0, 0, 14)),
        label("ItemName", name, BOLD, 15, "#ffffff", (0, 8, 0, 102), (1, -16, 0, 18),
              TextTruncate=token(1) if i != 4 else token(0)),
        I("TextButton", "Buy",
          # No UIGradient here: in Roblox a gradient tints a button's text too.
          corner(8),
          stroke("#1b6b30", 1.5, border=True),
          Text=price, FontFace=font(BOLD), TextSize=16.0, TextColor3=rgb("#ffffff"),
          Position=udim2(0.5, 0, 1, -12), AnchorPoint=vec2(0.5, 1), Size=udim2(1, -24, 0, 30),
          BackgroundColor3=rgb("#3cc95f"), BorderSizePixel=token(0), AutoButtonColor=True),
        BackgroundColor3=rgb("#ffffff"), BorderSizePixel=token(0), LayoutOrder=i,
    )


def tab(name: str, order: int, active: bool) -> I:
    return I("TextButton", name,
             corner(8),
             Text=name.upper(), FontFace=font(BOLD), TextSize=13.0,
             TextColor3=rgb("#101318" if active else "#b8c2cc"),
             BackgroundColor3=rgb("#ffcf4d" if active else "#2a313b"),
             Size=udim2(0, 96, 0, 30), BorderSizePixel=token(0), LayoutOrder=order)


def shop() -> I:
    return I(
        "ScreenGui", "ShopGui",
        I("Frame", "Shop",
          corner(18),
          stroke("#3a4452", 2, border=True),
          I("UIGradient", "UIGradient", Color=seq((0, "#1f252e"), (1, "#14181e")), Rotation=90.0),
          label("Title", "ITEM SHOP", BLACK, 28, "#ffffff", (0, 24, 0, 18), (0, 300, 0, 30), align=0),
          label("Subtitle", "New items every day", MEDIUM, 14, "#8b96a3", (0, 24, 0, 50), (0, 300, 0, 18),
                align=0),
          # coins
          I("Frame", "Coins",
            corner(0, 1.0),
            I("Frame", "Coin", corner(0, 1.0), stroke("#b8860b", 2, border=True),
              Position=udim2(0, 4, 0.5, 0), AnchorPoint=vec2(0, 0.5), Size=udim2(0, 26, 0, 26),
              BackgroundColor3=rgb("#ffcf4d"), BorderSizePixel=token(0)),
            label("Amount", "12,480", BOLD, 18, "#ffcf4d", (0, 38, 0, 0), (1, -46, 1, 0), align=0),
            Position=udim2(1, -76, 0, 24), AnchorPoint=vec2(1, 0), Size=udim2(0, 150, 0, 34),
            BackgroundColor3=rgb("#2a313b"), BorderSizePixel=token(0)),
          # close button
          I("TextButton", "Close", corner(0, 1.0), stroke("#8a1f2d", 2, border=True),
            Text="X", FontFace=font(BLACK), TextSize=18.0, TextColor3=rgb("#ffffff"),
            Position=udim2(1, -22, 0, 24), AnchorPoint=vec2(1, 0), Size=udim2(0, 34, 0, 34),
            BackgroundColor3=rgb("#e5484d"), BorderSizePixel=token(0)),
          # tabs
          I("Frame", "Tabs",
            I("UIListLayout", "UIListLayout", FillDirection=token(0), Padding=udim(0, 8),
              SortOrder=token(2)),
            tab("Weapons", 1, True), tab("Pets", 2, False), tab("Boosts", 3, False),
            Position=udim2(0, 24, 0, 82), Size=udim2(1, -48, 0, 30), BackgroundTransparency=1.0),
          # item grid
          I("Frame", "Items",
            I("UIGridLayout", "UIGridLayout", CellSize=udim2(0, 164, 0, 186),
              CellPadding=udim2(0, 14, 0, 14), SortOrder=token(2), FillDirectionMaxCells=3,
              HorizontalAlignment=token(0)),
            *[item_card(i, *item) for i, item in enumerate(ITEMS)],
            Position=udim2(0, 24, 0, 128), Size=udim2(1, -48, 1, -148), BackgroundTransparency=1.0),
          AnchorPoint=vec2(0.5, 0.5), Position=udim2(0.5, 0, 0.5, 0), Size=udim2(0, 568, 0, 540),
          BackgroundColor3=rgb("#ffffff"), BorderSizePixel=token(0)),
        ZIndexBehavior=token(1),
    )


# --- the 3D build ------------------------------------------------------------------

MATERIAL = {"Plastic": 256, "SmoothPlastic": 272, "Neon": 288, "Wood": 512, "WoodPlanks": 528,
            "Slate": 800, "Concrete": 816, "Brick": 848, "Cobblestone": 880, "Metal": 1088,
            "Glass": 1568, "Grass": 1280}


def part(name: str, pos, size, color: str, material: str = "Plastic", *children, cls: str = "Part",
         yaw: float = 0.0, **props) -> I:
    return I(cls, name, *children, CFrame=cframe(*pos, yaw), Size=vec3(*size), Color=rgb(color),
             Material=token(MATERIAL[material]), Anchored=True, **props)


def tower() -> list[I]:
    # The front of the build faces +Z, towards the standard iso camera.
    parts = [
        part("Base", (0, 1, 0), (18, 2, 18), "#7d7f82", "Cobblestone"),
        part("Walls", (0, 8, 0), (12, 12, 12), "#c9b79c", "Brick"),
        part("Door", (0, 5, 6.05), (3, 6, 0.2), "#6b4226", "WoodPlanks"),
        part("WindowL", (-3.4, 9.5, 6.05), (2, 2.6, 0.2), "#9fd3ff", "Glass", Transparency=0.3),
        part("WindowR", (3.4, 9.5, 6.05), (2, 2.6, 0.2), "#9fd3ff", "Glass", Transparency=0.3),
        part("Eaves", (0, 14.5, 0), (14, 1, 14), "#5a3e2b", "Wood"),
        # A WedgePart rises towards its local +Z; turning it 90 degrees makes the two
        # halves of a gable roof whose ridge runs front to back.
        part("RoofL", (-3.5, 17, 0), (14, 4, 7), "#8e2b2b", "Slate", cls="WedgePart", yaw=90),
        part("RoofR", (3.5, 17, 0), (14, 4, 7), "#8e2b2b", "Slate", cls="WedgePart", yaw=-90),
        part("Sign", (0, 12.8, 6.25), (8, 1.8, 0.3), "#2b2f36", "SmoothPlastic",
             I("SurfaceGui", "SignGui",
               label("Text", "TOWER SHOP", BLACK, 56, "#ffcf4d", (0, 0, 0, 0), (1, 0, 1, 0)),
               Face=token(2), SizingMode=token(1), PixelsPerStud=50.0)),
        part("Lamp", (7.5, 5, 7.5), (0.6, 6, 0.6), "#2b2f36", "Metal"),
        part("LampGlow", (7.5, 8.4, 7.5), (1.2, 1.2, 1.2), "#ffd36b", "Neon",
             I("PointLight", "PointLight", Color=rgb("#ffcf80"), Brightness=2.0, Range=16.0)),
        part("Crate1", (-6.8, 3, 7), (2, 2, 2), "#a0703f", "WoodPlanks"),
        part("Crate2", (-6.9, 5, 6.8), (2, 2, 2), "#8f6236", "WoodPlanks", yaw=20),
        part("Bush", (-7.5, 3.2, -6.5), (3, 3, 3), "#3f8f3f", "Grass", Shape=token(0)),
    ]
    npc_head = part("Head", (3.5, 6, 9.5), (2, 2, 2), "#f2c79a", "SmoothPlastic",
                    I("BillboardGui", "NameTag",
                      I("Frame", "Plate", corner(8),
                        label("Name", "Shopkeeper", BOLD, 20, "#ffffff", (0, 0, 0, 0), (1, 0, 1, 0)),
                        Size=udim2(1, 0, 1, 0), BackgroundColor3=rgb("#14181e"),
                        BackgroundTransparency=0.2, BorderSizePixel=token(0)),
                      Size=udim2(0, 150, 0, 34), StudsOffset=vec3(0, 2.4, 0), AlwaysOnTop=True))
    npc_body = part("Torso", (3.5, 3.5, 9.5), (2, 3, 1), "#2f6fb0", "SmoothPlastic")
    workspace = I(
        "Workspace", "Workspace",
        part("Baseplate", (0, -8, 0), (2048, 16, 2048), "#6b9e4f", "Grass", Locked=True),
        I("Model", "Tower", *parts),
        I("Model", "Shopkeeper", npc_head, npc_body),
    )
    lighting = I("Lighting", "Lighting", ClockTime=15.2, GeographicLatitude=41.7, Brightness=2.0,
                 Ambient=rgb("#46464c"), OutdoorAmbient=rgb("#80808a"), GlobalShadows=True)
    return [workspace, lighting]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    write(OUT / "shop.rbxmx", shop())
    write(OUT / "tower.rbxmx", *tower())


if __name__ == "__main__":
    main()
