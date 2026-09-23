"""roblox-headless-renderer: headless previews of Roblox UI and 3D builds."""


def __getattr__(name: str):
    # Looked up lazily: importlib.metadata costs ~70 ms on every `rhr` start.
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("roblox-headless-renderer")
        except PackageNotFoundError:  # a source tree that was never installed
            return "0+unknown"
    raise AttributeError(name)
