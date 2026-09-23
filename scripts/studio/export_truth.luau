--!strict
-- RHR ground truth, recorded by Roblox Studio itself.
--
-- Paste this whole file into Studio's command bar (View > Command Bar) with the
-- place open in edit mode, press Enter, then save the place as a file
-- (File > Save to File As..., .rbxlx) into tests/studio/ in the RHR repository.
--
-- It records what Studio computed, not what the file says:
--   * every GuiObject under StarterGui: AbsolutePosition and AbsoluteSize (pixels),
--     and for text objects their TextBounds (the laid-out text's extent)
--   * every BasePart under Workspace: world position, orientation and Size (studs)
--   * the viewport size and the GUI inset, so RHR can lay out on the same canvas
-- and stores it as JSON in ServerStorage.RHRTruth (a StringValue), so the saved
-- file carries its own truth. `python scripts/studio/compare_truth.py <file>`
-- (and tests/test_studio_truth.py) compare RHR against it.
--
-- Paths follow RHR's rule: service name first, "/" between names, and siblings
-- that share a name are ALL indexed in child order: Card[1], Card[2].

local HttpService = game:GetService("HttpService")
local GuiService = game:GetService("GuiService")
local ServerStorage = game:GetService("ServerStorage")

local function segment(inst: Instance): string
	return if inst.Name ~= "" then inst.Name else inst.ClassName
end

local paths: { [Instance]: string } = {}
local function assignPaths(parent: Instance, parentPath: string)
	local children = parent:GetChildren()
	local counts: { [string]: number } = {}
	for _, child in children do
		counts[segment(child)] = (counts[segment(child)] or 0) + 1
	end
	local seen: { [string]: number } = {}
	for _, child in children do
		local name = segment(child)
		local part = name
		if counts[name] > 1 then
			seen[name] = (seen[name] or 0) + 1
			part = `{name}[{seen[name]}]`
		end
		local here = if parentPath == "" then part else `{parentPath}/{part}`
		paths[child] = here
		assignPaths(child, here)
	end
end
assignPaths(game, "")

local function round(value: number): number
	return math.round(value * 1000) / 1000
end

local gui = {}
for _, inst in game:GetService("StarterGui"):GetDescendants() do
	if inst:IsA("GuiObject") then
		gui[paths[inst]] = {
			x = round(inst.AbsolutePosition.X),
			y = round(inst.AbsolutePosition.Y),
			w = round(inst.AbsoluteSize.X),
			h = round(inst.AbsoluteSize.Y),
			visible = inst.Visible,
		}
		if inst:IsA("TextLabel") or inst:IsA("TextButton") or inst:IsA("TextBox") then
			gui[paths[inst]].text = { round(inst.TextBounds.X), round(inst.TextBounds.Y) }
		end
	end
end

local parts = {}
for _, inst in workspace:GetDescendants() do
	if inst:IsA("BasePart") and not inst:IsA("Terrain") then
		local position = inst.Position
		local orientation = inst.Orientation
		parts[paths[inst]] = {
			class = inst.ClassName,
			position = { round(position.X), round(position.Y), round(position.Z) },
			orientation = { round(orientation.X), round(orientation.Y), round(orientation.Z) },
			size = { round(inst.Size.X), round(inst.Size.Y), round(inst.Size.Z) },
		}
	end
end

local camera = workspace.CurrentCamera
local inset = GuiService:GetGuiInset()
local truth = {
	format = "rhr-studio-truth/1",
	studioVersion = version(),
	viewport = { round(camera.ViewportSize.X), round(camera.ViewportSize.Y) },
	guiInset = { round(inset.X), round(inset.Y) },
	camera = {
		position = { round(camera.CFrame.Position.X), round(camera.CFrame.Position.Y), round(camera.CFrame.Position.Z) },
		lookVector = { round(camera.CFrame.LookVector.X), round(camera.CFrame.LookVector.Y), round(camera.CFrame.LookVector.Z) },
		fieldOfView = round(camera.FieldOfView),
	},
	gui = gui,
	parts = parts,
}

local store = ServerStorage:FindFirstChild("RHRTruth")
if store and not store:IsA("StringValue") then
	store:Destroy()
	store = nil
end
if not store then
	store = Instance.new("StringValue")
	store.Name = "RHRTruth"
	store.Parent = ServerStorage
end
(store :: StringValue).Value = HttpService:JSONEncode(truth)

local guiCount, partCount = 0, 0
for _ in gui do guiCount += 1 end
for _ in parts do partCount += 1 end
print(`RHR truth recorded: {guiCount} GUI objects, {partCount} parts, viewport {truth.viewport[1]}x{truth.viewport[2]}. Now save the place to a file.`)
