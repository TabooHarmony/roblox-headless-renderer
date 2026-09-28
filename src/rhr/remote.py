"""Roblox assets as inputs: `rhr scene 2810302648`, a Creator Store link, ...

Anywhere a command takes a file it also takes an asset reference, when no file of
that name exists:

    2810302648                                        an asset id
    rbxassetid://2810302648
    https://create.roblox.com/store/asset/2810302648/...   Creator Store
    https://www.roblox.com/library/2810302648/...         the old library link
    https://www.roblox.com/catalog/2810302648/...         avatar items
    https://www.roblox.com/games/1234/...                 a place (only your own)

The asset is downloaded the way `rhr.fetch` downloads meshes (the Studio login, then
what Roblox serves without one) into <cache>/cache/models/<id>.rbxm (.rbxl for a
place, .rbxmx/.rbxlx when Roblox serves XML), and the command runs on that file. It
is used again without asking Roblox for 10 minutes; after that one request checks
whether the asset changed (Roblox's link names the content), and only a changed asset
is downloaded again. Default outputs are named after the id: `2810302648-scene.png`.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

from rhr.paths import CACHE

MODEL_CACHE = CACHE / "cache" / "models"
REVALIDATE_AFTER = 10 * 60
PLACE_TYPE = 9
# Asset types that are not a model or place, for the message when one is given.
TYPE_NAMES = {
    1: "an image", 2: "a T-shirt", 3: "an audio file", 4: "a mesh", 5: "a script", 11: "a shirt",
    12: "pants", 13: "a decal", 18: "a face", 21: "a badge", 24: "an animation", 34: "a game pass",
    39: "a union's geometry", 40: "a MeshPart's mesh", 62: "a video", 73: "a font family",
}

_PATTERNS = [
    re.compile(r"^(\d{1,20})$"),
    re.compile(r"^rbxassetid://(\d{1,20})$", re.I),
    re.compile(r"^(?:https?://)?create\.roblox\.com/(?:store|marketplace)/asset/(\d{1,20})(?:[/?#].*)?$", re.I),
    re.compile(r"^(?:https?://)?(?:www\.|web\.)?roblox\.com/(?:library|catalog|games)/(\d{1,20})(?:[/?#].*)?$", re.I),
    re.compile(r"^(?:https?://)?assetdelivery\.roblox\.com/v1/asset/?\?id=(\d{1,20})$", re.I),
]


class AssetError(ValueError):
    """An asset reference that could not be turned into a file (the message says why)."""


def asset_reference(text: str) -> str | None:
    """The asset id `text` names (an id, rbxassetid:// or a Roblox link), else None."""
    text = text.strip()
    for pattern in _PATTERNS:
        match = pattern.match(text)
        if match:
            return str(int(match.group(1)))
    return None


def _meta_path(asset: str) -> Path:
    return MODEL_CACHE / f"{asset}.json"


def _load_meta(asset: str) -> dict:
    try:
        return json.loads(_meta_path(asset).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _content_key(location: str) -> str:
    return location.split("?", 1)[0]  # the CDN path names the content; the query is the signature


def _details(asset: str, out: dict) -> None:
    """Name, type and creator from Roblox's public catalog details (best effort)."""
    request = urllib.request.Request(f"https://economy.roblox.com/v2/assets/{asset}/details",
                                     headers={"User-Agent": "roblox-headless-renderer"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
        out["name"] = str(data.get("Name") or "")
        out["creator"] = str((data.get("Creator") or {}).get("Name") or "")
        out["type"] = data.get("AssetTypeId")
    except Exception:  # noqa: BLE001 - only used for a friendlier line on stderr
        pass


def _answer(asset: str, *, login: bool) -> dict:
    """Where the asset is: {location, type} or {why}, trying the login first."""
    from rhr import fetch

    reason = None
    if login:
        answers = fetch.answers_signed_in([asset])
        if isinstance(answers, dict):
            answer = answers.get(asset) or {}
            if answer.get("location"):
                return answer
            code = int(answer.get("code") or 0)
            if code not in (401, 403) or "approved" in str(answer.get("message", "")):
                return {"why": _refusal(asset, code, str(answer.get("message") or "no answer"), signed_in=True)}
        else:
            reason = answers
    answer = fetch.answers_public([asset]).get(asset) or {}
    if answer.get("location"):
        return answer
    code = int(answer.get("code") or 0)
    if code in (401, 403):
        if reason == fetch._NO_LOGIN or not login:
            return {"why": f"asset {asset} needs a signed-in account: sign in to Roblox Studio on "
                           "this machine and try again"}
        if reason:
            return {"why": f"asset {asset} needs a signed-in account, and the Studio login could "
                           f"not be used: {reason.removeprefix('missing (').removesuffix(')')}"}
    return {"why": _refusal(asset, code, str(answer.get("message") or "no answer"), signed_in=False)}


def _refusal(asset: str, code: int, message: str, *, signed_in: bool) -> str:
    if code == 404:
        return f"Roblox has no asset {asset}"
    if code == 403 and "approved" in message:
        return (f"Roblox will not give asset {asset} to this account ({message}): it is private, "
                "not free, or moderated")
    if code == 409 and "authorized" in message.lower():
        return (f"Roblox will not give asset {asset} to this account ({message}): a place can be "
                "downloaded only by people who can edit it, a private model only by its owner")
    who = "the signed-in account" if signed_in else "anyone without a login"
    return f"Roblox refused asset {asset} to {who}: " + (f"HTTP {code}: {message}" if code else message)


def _suffix(payload: bytes, asset_type) -> str:
    place = asset_type == PLACE_TYPE
    if payload.startswith(b"<roblox!"):
        return ".rbxl" if place else ".rbxm"
    if payload.lstrip()[:7].lower() == b"<roblox":
        return ".rbxlx" if place else ".rbxmx"
    return ""


def _what(payload: bytes, asset_type) -> str:
    if asset_type in TYPE_NAMES:
        return TYPE_NAMES[asset_type]
    if payload.startswith(b"version "):
        return "a mesh"
    if payload[:8] == b"\x89PNG\r\n\x1a\n" or payload[:3] == b"\xff\xd8\xff":
        return "an image"
    return f"asset type {asset_type}" if asset_type else "not a Roblox model"


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def resolve(text: str, *, login: bool = True, log=_say) -> Path:
    """The local file for the asset `text` names, downloading it when needed."""
    from rhr import fetch

    asset = asset_reference(text)
    if asset is None:
        raise AssetError(f"not an asset id or Roblox link: {text}")
    meta = _load_meta(asset)
    cached = MODEL_CACHE / f"{asset}{meta.get('suffix', '')}" if meta.get("suffix") else None
    fresh = cached is not None and cached.is_file() and time.time() - meta.get("checked", 0) < REVALIDATE_AFTER
    if cached is not None and cached.is_file() and (fresh or fetch.offline()):
        log(f"asset  {asset}  {_label(meta)}(cached)")
        return cached
    if fetch.offline():
        raise AssetError(f"asset {asset} is not in the cache and downloads are off (--offline)")

    details: dict = {}
    lookup = threading.Thread(target=_details, args=(asset, details), daemon=True)
    lookup.start()
    answer = _answer(asset, login=login)
    if "why" in answer:
        raise AssetError(answer["why"])
    key = _content_key(answer["location"])
    lookup.join(timeout=5)
    meta.update({k: v for k, v in details.items() if v})
    meta["type"] = answer.get("type") or meta.get("type")
    if cached is not None and cached.is_file() and meta.get("key") == key:
        meta["checked"] = time.time()
        _save_meta(asset, meta)
        log(f"asset  {asset}  {_label(meta)}(cached, unchanged)")
        return cached

    payload = fetch._download(answer["location"])
    if isinstance(payload, str):
        raise AssetError(f"asset {asset}: {payload.removeprefix('missing (').removesuffix(')')}")
    suffix = _suffix(payload, meta.get("type"))
    if not suffix:
        raise AssetError(f"asset {asset} is {_what(payload, meta.get('type'))}, not a model or place: "
                         "RHR draws models and places")
    target = MODEL_CACHE / f"{asset}{suffix}"
    fetch._write(target, payload)
    if cached is not None and cached != target:
        cached.unlink(missing_ok=True)
    meta.update({"key": key, "suffix": suffix, "checked": time.time(), "size": len(payload)})
    _save_meta(asset, meta)
    size = f"{len(payload) / 1e6:.1f} MB" if len(payload) >= 100_000 else f"{len(payload) / 1e3:.0f} KB"
    log(f"asset  {asset}  {_label(meta)}{size} downloaded")
    return target


def _label(meta: dict) -> str:
    name = meta.get("name")
    if not name:
        return ""
    return f"\"{name}\"" + (f" by {meta['creator']}" if meta.get("creator") else "") + "  "


def _save_meta(asset: str, meta: dict) -> None:
    from rhr import fetch

    fetch._write(_meta_path(asset), json.dumps(meta, sort_keys=True).encode())
