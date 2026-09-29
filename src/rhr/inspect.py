"""`rhr inspect`: what a Roblox file holds, and what its scripts would do when run.

Before inserting a free model, or opening a file from someone else: how many
instances of which classes, which scripts (path, lines, disabled), which assets it
uses, and findings for code that is a known way in for backdoors and scams. RHR
never runs the scripts; it reads their source.

    require-by-id      require(<number>): loads code from Roblox when the game runs,
                       code nobody can see in the file (error: the classic backdoor)
    fenv               getfenv / setfenv: rewrites other code's globals (warning)
    loadstring         runs text as code (warning)
    obfuscated         lines thousands of characters long, or mostly \\ddd escapes /
                       string.char runs: code hiding what it does (warning)
    webhook            sends data out: a Discord webhook or an HttpService post (warning)
    load-asset         InsertService:LoadAsset: inserts more models at run time (warning)
    purchase-prompt    prompts a purchase (info: fine in a game, odd in a free model)
    teleport           TeleportService: sends players to another place (info)
    virus-name         a script named like the old self-copying viruses (info)

JSON: `rhr.inspect/1`. The findings are reasons to look, not verdicts.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript"}
ASSET_KINDS = ("images", "meshes", "sounds", "animations")
# Binary files keep references under the new *Content names, XML files under the old.
_IMAGE_PROPS = {"Image", "Texture", "TextureID", "TextureId", "ColorMap", "NormalMap", "RoughnessMap",
                "MetalnessMap", "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp",
                "ShirtTemplate", "PantsTemplate", "Graphic", "HoverImage", "PressedImage", "SunTextureId",
                "MoonTextureId"}


def _asset_kind(prop: str) -> str | None:
    if prop in ("MeshId", "MeshContent"):
        return "meshes"
    if prop in ("SoundId", "AudioContent"):
        return "sounds"
    if prop in ("AnimationId", "AnimationContent"):
        return "animations"
    if prop in _IMAGE_PROPS or (prop.endswith("Content") and not prop.startswith(("CursorIcon", "Cage", "Reference"))):
        return "images"
    return None
_ASSET_ID = re.compile(r"(?:rbxassetid://|roblox\.com/asset/?\?id=|^)(\d{3,20})$", re.I)
VIRUS_NAMES = {"vaccine", "infection", "spread", "virus", "anti lag", "antilag", "snap reducer", "4d being",
               "ew", "rofl", "fix", "lag fix"}

_CHECKS = [
    # A number (decimal or 0x hex, maybe summed, maybe through tonumber("...")), not a path.
    ("require-by-id", "error",
     re.compile(r"\brequire\s*\(\s*(?:tonumber\s*\(\s*)?[\"']?(?:0x[0-9a-fA-F]{4,}|\d[\d_ +\-*/]{4,})[\"']?\s*\)+"),
     "{} loads code from Roblox when the game runs: code that is not in this file"),
    ("fenv", "warning", re.compile(r"\b(?:getfenv|setfenv)\s*\("), "{} rewrites or reads other code's globals"),
    ("loadstring", "warning", re.compile(r"\bloadstring\s*\("), "{} runs text as code"),
    ("webhook", "warning", re.compile(r"discord(?:app)?\.com/api/webhooks|webhook|:\s*PostAsync\s*\(|:\s*RequestAsync\s*\("),
     "{}: sends data out of the game"),
    ("load-asset", "warning", re.compile(r":\s*LoadAsset(?:Version)?\s*\("), "{} inserts more models when the game runs"),
    ("purchase-prompt", "info", re.compile(r":\s*Prompt(?:Product|GamePass|Premium|Bundle)?Purchase\s*\("),
     "{} prompts a purchase"),
    ("teleport", "info", re.compile(r"TeleportService|:\s*TeleportAsync\s*\("), "{}: sends players to another place"),
]


class Node:
    """One instance, whichever reader found it."""

    __slots__ = ("class_name", "name", "children", "props", "path")

    def __init__(self, class_name: str, name: str):
        self.class_name, self.name = class_name, name
        self.children: list[Node] = []
        self.props: dict[str, object] = {}
        self.path = ""


def _from_binary(data: bytes) -> list[Node]:
    from rhr.rbx import binary

    doc = binary.read(data)
    wanted: dict[int, list[str]] = {}  # per class group: which of its properties to read

    def convert(instance) -> Node:
        node = Node(instance.class_name, instance.name)
        props = wanted.get(id(instance.group))
        if props is None:
            props = wanted[id(instance.group)] = [
                prop for prop in instance.names()
                if prop == "Source" or prop in ("Disabled", "Enabled", "RunContext") or _asset_kind(prop)]
        for prop in props:
            value = getattr(instance.get(prop), "value", None)
            if value is None:
                continue
            if isinstance(value, tuple) and len(value) == 2:  # Content: ("uri", url)
                value = value[1]
            node.props[prop] = value
        node.children = [convert(child) for child in instance.children]
        return node

    return [convert(root) for root in doc.roots]


def _from_xml(data: bytes) -> list[Node]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(data)

    def convert(item) -> Node:
        properties = item.find("Properties")
        name = ""
        node = Node(item.get("class", "?"), "")
        if properties is not None:
            for prop in properties:
                key = prop.get("name", "")
                if key == "Name":
                    name = prop.text or ""
                elif key == "Source" or key in ("Disabled", "Enabled", "RunContext") or _asset_kind(key):
                    url = prop.find("url")
                    node.props[key] = (url.text if url is not None else prop.text) or ""
        node.name = name
        node.children = [convert(child) for child in item.findall("Item")]
        return node

    return [convert(item) for item in root.findall("Item")]


def _name_paths(nodes: list[Node], parent: str = "") -> None:
    """`Model/Child/Grandchild`, same-named siblings as `Card[1]`, `Card[2]` (as rhr.ir)."""
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node.name or node.class_name] = counts.get(node.name or node.class_name, 0) + 1
    seen: dict[str, int] = {}
    for node in nodes:
        segment = node.name or node.class_name
        if counts[segment] > 1:
            seen[segment] = seen.get(segment, 0) + 1
            segment = f"{segment}[{seen[segment]}]"
        node.path = f"{parent}/{segment}" if parent else segment
        _name_paths(node.children, node.path)


def _walk(nodes: list[Node]):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def read(source: Path) -> list[Node]:
    data = source.read_bytes()
    if data.startswith(b"<roblox!"):
        roots = _from_binary(data)
    elif data.lstrip()[:7].lower() == b"<roblox":
        roots = _from_xml(data)
    else:
        raise ValueError(f"{source} is not a Roblox model or place file")
    _name_paths(roots)
    return roots


def _truthy(value) -> bool:
    return value is True or str(value).lower() == "true"


def script_findings(path: str, source: str) -> list[dict]:
    findings = []
    for number, line in enumerate(source.splitlines(), 1):
        for check, severity, pattern, text in _CHECKS:
            match = pattern.search(line)
            if match:
                shown = re.sub(r"\s+", "", match.group(0))[:60]
                findings.append({"check": check, "severity": severity, "path": path, "line": number,
                                 "detail": text.format(shown)})
        # (A long comment or prose line hides nothing: it has to be dense with code characters.)
        if len(line) > 2000 and not line.lstrip().startswith("--") and sum(
                line.count(c) for c in "()[];=\\") > len(line) / 25:
            findings.append({"check": "obfuscated", "severity": "warning", "path": path, "line": number,
                             "detail": f"a line {len(line)} characters long: code hiding what it does"})
    escapes = len(re.findall(r"\\\d{1,3}", source))
    chars = len(re.findall(r"string\.char\s*\(|\bchar\s*\(", source))
    if len(source) > 200 and (escapes * 4 > len(source) * 0.3 or chars > 30):
        findings.append({"check": "obfuscated", "severity": "warning", "path": path, "line": None,
                         "detail": f"mostly escaped characters ({escapes} \\ddd escapes, {chars} string.char calls)"})
    # One finding per check and line is plenty.
    unique, seen = [], set()
    for finding in findings:
        key = (finding["check"], finding["line"])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def inspect(source: Path) -> dict:
    from rhr.schema import stamp

    roots = read(source)
    class_counts: dict[str, int] = {}
    scripts, findings = [], []
    assets: dict[str, set[str]] = {kind: set() for kind in ASSET_KINDS}
    for node in _walk(roots):
        class_counts[node.class_name] = class_counts.get(node.class_name, 0) + 1
        for prop, value in node.props.items():
            kind = _asset_kind(prop)
            match = _ASSET_ID.search(str(value or "").strip()) if kind else None
            if match:
                assets[kind].add(match.group(1))
        if node.class_name in SCRIPT_CLASSES:
            text = str(node.props.get("Source") or "")
            scripts.append({
                "path": node.path,
                "className": node.class_name,
                "lines": text.count("\n") + 1 if text else 0,
                "bytes": len(text.encode("utf-8")),
                "disabled": _truthy(node.props.get("Disabled")) or node.props.get("Enabled") is False,
            })
            findings += script_findings(node.path, text)
            if node.name.strip().lower() in VIRUS_NAMES:
                findings.append({"check": "virus-name", "severity": "info", "path": node.path, "line": None,
                                 "detail": f"a {node.class_name} named {node.name!r}, like the old self-copying viruses"})
    services = {"Workspace", "Lighting", "ReplicatedStorage", "ServerScriptService", "StarterGui"}
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f["path"], f["line"] or 0))
    return stamp("inspect", {
        "source": str(source),
        "kind": "place" if any(root.class_name in services for root in roots) else "model",
        "instances": sum(class_counts.values()),
        "classCounts": dict(sorted(class_counts.items(), key=lambda item: (-item[1], item[0]))),
        "roots": [{"path": root.path, "className": root.class_name} for root in roots],
        "scripts": scripts,
        "assets": {kind: sorted(ids, key=lambda value: (len(value), value)) for kind, ids in assets.items()},
        "findings": findings,
    })
