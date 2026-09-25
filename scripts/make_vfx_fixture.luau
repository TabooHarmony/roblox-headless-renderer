-- Writes tests/fixtures/vfx_played.rbxm, made for this repository:
--
--     lune run scripts/make_vfx_fixture.luau
--
-- Two red emitters that a script would play (disabled; EmitCount 40 at EmitDelay 0.5),
-- one each side of the origin, with a black wall in front of the left one when seen
-- from (0, 5, 30). A green emitter that is simply running, above them, on an
-- attachment turned to fire sideways (+X). A disabled emitter without attributes,
-- which is not drawn and is reported.
local fs = require("@lune/fs")
local roblox = require("@lune/roblox")
local Instance = roblox.Instance
local Vector3 = roblox.Vector3
local CFrame = roblox.CFrame
local Color3 = roblox.Color3
local NumberRange = roblox.NumberRange
local NumberSequence = roblox.NumberSequence
local ColorSequence = roblox.ColorSequence
local Enum = roblox.Enum

local model = Instance.new("Model")
model.Name = "VfxPlayed"

local function part(name, position, size, transparency, color)
	local p = Instance.new("Part")
	p.Name = name
	p.Anchored = true
	p.Size = size
	p.CFrame = CFrame.new(position.X, position.Y, position.Z)
	p.Transparency = transparency
	p.Color = color
	p.Material = Enum.Material.SmoothPlastic
	p.Parent = model
	return p
end

local function emitter(parent, name, color)
	local e = Instance.new("ParticleEmitter")
	e.Name = name
	e.Texture = ""
	e.Color = ColorSequence.new(color)
	e.Size = NumberSequence.new(1.5)
	e.Transparency = NumberSequence.new(0)
	e.Lifetime = NumberRange.new(1, 1)
	e.Speed = NumberRange.new(2, 2)
	e.SpreadAngle = roblox.Vector2.new(180, 180)
	e.LightEmission = 1
	e.Rate = 20
	e.Parent = parent
	return e
end

for _, x in { -6, 6 } do
	local source = part(if x < 0 then "LeftSource" else "RightSource", Vector3.new(x, 5, 0), Vector3.new(1, 1, 1), 1, Color3.new(1, 1, 1))
	local burst = emitter(source, "Burst", Color3.new(1, 0.1, 0.1))
	burst.Enabled = false
	burst:SetAttribute("EmitCount", 40)
	burst:SetAttribute("EmitDelay", 0.5)
end

part("Wall", Vector3.new(-6, 5, 10), Vector3.new(8, 8, 1), 0, Color3.new(0, 0, 0))

local holder = part("Holder", Vector3.new(0, 14, 0), Vector3.new(1, 1, 1), 1, Color3.new(1, 1, 1))
local attachment = Instance.new("Attachment")
attachment.Name = "Sideways"
-- Turned -90 degrees about Z, so its Top (+Y) points along world +X.
attachment.CFrame = CFrame.Angles(0, 0, -math.pi / 2)
attachment.Parent = holder
local stream = emitter(attachment, "Stream", Color3.new(0.1, 1, 0.1))
stream.SpreadAngle = roblox.Vector2.new(0, 0)
stream.Speed = NumberRange.new(6, 6)

local idle = emitter(holder, "PlayedByScript", Color3.new(0.1, 0.1, 1))
idle.Enabled = false

fs.writeFile("tests/fixtures/vfx_played.rbxm", roblox.serializeModel({ model }))
print("wrote tests/fixtures/vfx_played.rbxm")
