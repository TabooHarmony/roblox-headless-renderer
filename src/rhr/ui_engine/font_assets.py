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


def resolve_font_family(family_url: str) -> str:
    """Resolve an rbxassetid:// font URL to a family name.

    Uses a local cache, then falls back to the Roblox API for unknown IDs (not
    offline: RHR_OFFLINE=1 or `--offline`).
    Returns the original URL unchanged if resolution fails.
    """
    m = _RBXASSETID_RE.search(family_url)
    if not m:
        return family_url
    aid = m.group(1)
    if aid in _FONT_ASSET_CACHE:
        return _FONT_ASSET_CACHE[aid]
    from rhr.fetch import offline

    if offline():
        return family_url
    # API fallback
    try:
        resp = requests.get(
            "https://apis.roblox.com/toolbox-service/v1/items/details",
            params={"assetIds": aid},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            name = item.get("asset", {}).get("name", "")
            if name:
                _FONT_ASSET_CACHE[aid] = name
                return name
    except Exception:
        pass
    return family_url
