-- Writes tests/fixtures/highlight.rbxm, made for this repository:
--
--     lune run scripts/make_highlight_fixture.luau
--
-- Two cubes behind a grey wall, seen from (0, 5, 30). The left cube's Highlight is
-- AlwaysOnTop (blue fill, yellow outline), so it shows through the wall; the right
-- one's is Occluded (red fill), so the wall hides it.
local fs = require("@lune/fs")
local roblox = require("@lune/roblox")
local Instance, Vector3, CFrame, Color3 = roblox.Instance, roblox.Vector3, roblox.CFrame, roblox.Color3
local Enum = roblox.Enum

local model = Instance.new("Model")
model.Name = "HighlightFixture"

local function part(name, position, size, color)
	local p = Instance.new("Part")
	p.Name = name
	p.Anchored = true
	p.Size = size
	p.CFrame = CFrame.new(position.X, position.Y, position.Z) * CFrame.Angles(0.3, 0.5, 0)
	p.Color = color
	p.Material = Enum.Material.SmoothPlastic
	p.Parent = model
	return p
end

local left = part("OnTop", Vector3.new(-5, 5, 0), Vector3.new(5, 5, 5), Color3.fromRGB(200, 200, 200))
local h1 = Instance.new("Highlight")
h1.FillColor = Color3.fromRGB(0, 60, 255)
h1.FillTransparency = 0
h1.OutlineColor = Color3.fromRGB(255, 230, 0)
h1.OutlineTransparency = 0
h1.DepthMode = Enum.HighlightDepthMode.AlwaysOnTop
h1.Parent = left

local right = part("Occluded", Vector3.new(5, 5, 0), Vector3.new(5, 5, 5), Color3.fromRGB(200, 200, 200))
local h2 = Instance.new("Highlight")
h2.FillColor = Color3.fromRGB(255, 0, 0)
h2.FillTransparency = 0
h2.OutlineTransparency = 1
h2.DepthMode = Enum.HighlightDepthMode.Occluded
h2.Parent = right

local wall = Instance.new("Part")
wall.Name = "Wall"
wall.Anchored = true
wall.Size = Vector3.new(24, 12, 1)
wall.CFrame = CFrame.new(0, 5, 8)
wall.Color = Color3.fromRGB(120, 120, 120)
wall.Material = Enum.Material.SmoothPlastic
wall.Parent = model

fs.writeFile("tests/fixtures/highlight.rbxm", roblox.serializeModel({ model }))
print("wrote tests/fixtures/highlight.rbxm")
