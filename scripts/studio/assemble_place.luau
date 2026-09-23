-- Turn an .rbxm exported from Studio into a place file for tests/studio/.
--
--   lune run scripts/studio/assemble_place.luau <export.rbxm> <out.rbxlx> [Service=Name ...]
--
-- Studio MCP exports selected instances as a model, which loses the services they
-- lived in. Each root goes back under its service: the RHRTruth StringValue under
-- ServerStorage, GUI containers (ScreenGui) under StarterGui, everything else under
-- Workspace unless an explicit `Service=Name` argument says otherwise. The truth's
-- paths start at the service, so the place must reproduce that layout exactly.
local fs = require("@lune/fs")
local process = require("@lune/process")
local roblox = require("@lune/roblox")

local source, out = process.args[1], process.args[2]
if not source or not out then
	print("usage: lune run scripts/studio/assemble_place.luau <export.rbxm> <out.rbxlx> [Service=Name ...]")
	process.exit(1)
end
local overrides = {}
for index = 3, #process.args do
	local service, name = string.match(process.args[index], "^(%w+)=(.+)$")
	if service then overrides[name] = service end
end

local game = roblox.Instance.new("DataModel")
local roots = roblox.deserializeModel(fs.readFile(source))
local placed = {}
local SERVICE_ROOTS = { Lighting = true }
for _, root in roots do
	-- An exported service (Lighting, with its Sky/Atmosphere children) becomes the
	-- place's service itself, properties included.
	if SERVICE_ROOTS[root.ClassName] then
		root.Parent = game
		table.insert(placed, root.ClassName)
		continue
	end
	local service = overrides[root.Name]
		or (root.Name == "RHRTruth" and root.ClassName == "StringValue" and "ServerStorage")
		or (root.ClassName == "ScreenGui" and "StarterGui")
		or "Workspace"
	root.Parent = game:GetService(service)
	table.insert(placed, service .. "/" .. root.Name)
end
fs.writeFile(out, roblox.serializePlace(game, true))
print("wrote " .. out .. ": " .. table.concat(placed, ", "))
