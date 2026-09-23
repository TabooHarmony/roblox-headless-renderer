# Studio-recorded fixtures

Each place here was built in Roblox Studio and carries the ground truth Studio
computed for it, in `ServerStorage.RHRTruth`. `tests/test_studio_truth.py` checks
RHR against every place in this folder: GUI rects within 2 px, parts within
0.01 studs.

## Adding one

1. In Studio, build or open a place with the UI (under StarterGui) and/or parts
   (under Workspace) you want covered. Keep it small and focused: one idea per place.
2. Open View > Command Bar, paste all of `scripts/studio/export_truth.luau`, press
   Enter. It prints how many GUI objects and parts it recorded.
3. File > Save to File As..., save as `.rbxlx` into this folder with a descriptive
   name (for example `ui_list_layout.rbxlx`).
4. Run `python scripts/studio/compare_truth.py tests/studio/<name>.rbxlx` to see the
   result, then commit the file.

Only use content you made yourself or have the rights to publish: this folder is
meant to ship with the public repository.
