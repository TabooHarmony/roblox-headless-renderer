"""Font asset id -> family name, for fonts a file gives as `rbxassetid://<id>`."""

import re

import requests

_RBXASSETID_RE = re.compile(r"rbxassetid://(\d+)")

# Well-known Roblox built-in font families (avoids API calls for common fonts)
_FONT_ASSET_CACHE: dict[str, str] = {
    "11702779409": "Poppins",
    "11702779514": "Oswald",
    "11702779517": "Montserrat",
    "11702779556": "Lato",
    "12187370747": "Noto Sans",
    "12187371840": "Silkscreen",
    "12187374537": "Sono",
    "12187374954": "Fira Sans",
    "12187375181": "Merriweather",
    "12187375399": "Roboto",
    "12187375716": "Finger Paint",
    "12187375893": "Nunito",
    "16658221428": "Builder Sans",
    "16658233911": "Builder Sans Semi",
    "16658236243": "Builder Serif",
    "16658237174": "Builder Extended",
    "16658246179": "Builder Mono",
}


# Answers from Roblox, kept on disk: a name for good, "" (not found) for a day. Without
# it every UI command asked again for each uploaded font a file uses: 28 requests,
# about 8 s, on one real game, on every command.
_ASKED: dict[str, tuple[str, float]] | None = None
_RETRY_S = 24 * 3600


def _answers_path():
    from rhr.paths import CACHE

    return CACHE / "cache" / "font_names.json"


def _answers() -> dict[str, tuple[str, float]]:
    global _ASKED
    if _ASKED is None:
        import json

        try:
            raw = json.loads(_answers_path().read_text(encoding="utf-8"))
            _ASKED = {k: (str(v[0]), float(v[1])) for k, v in raw.items()}
        except (OSError, ValueError, TypeError, IndexError, KeyError):
            _ASKED = {}
    return _ASKED


def _remember(aid: str, name: str) -> None:
    import json
    import os
    import time

    answers = _answers()
    answers[aid] = (name, time.time())
    path = _answers_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.{os.getpid()}.part")
        partial.write_text(json.dumps(answers), encoding="utf-8")
        os.replace(partial, path)
    except OSError:
        pass


def resolve_font_family(family_url: str) -> str:
    """Resolve an rbxassetid:// font URL to a family name.

    Uses the built-in table, then what Roblox answered before (rhr cache), then asks
    Roblox's API (not offline: RHR_OFFLINE=1 or `--offline`). Returns the original
    URL unchanged if resolution fails.
    """
    import time

    m = _RBXASSETID_RE.search(family_url)
    if not m:
        return family_url
    aid = m.group(1)
    if aid in _FONT_ASSET_CACHE:
        return _FONT_ASSET_CACHE[aid]
    known = _answers().get(aid)
    if known is not None and (known[0] or time.time() - known[1] < _RETRY_S):
        return known[0] or family_url
    from rhr.fetch import offline

    if offline():
        return family_url
    name = ""
    try:
        resp = requests.get(
            "https://apis.roblox.com/toolbox-service/v1/items/details",
            params={"assetIds": aid},
            timeout=5,
        )
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            _remember(aid, "")  # Roblox's answer: no such font (an uploaded, private one)
            return family_url
        resp.raise_for_status()
        for item in resp.json().get("data", []):
            name = item.get("asset", {}).get("name", "") or name
            if name:
                break
    except Exception:  # noqa: BLE001 - a lookup that fails draws in the default face
        return family_url  # (not remembered: the network may be back next time)
    _remember(aid, name)
    return name or family_url
