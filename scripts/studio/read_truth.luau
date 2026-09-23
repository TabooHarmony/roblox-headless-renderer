-- Print the JSON that scripts/studio/export_truth.luau stored in a saved place.
--   lune run scripts/studio/read_truth.luau <place.rbxlx|.rbxl>
local fs = require("@lune/fs")
local process = require("@lune/process")
local roblox = require("@lune/roblox")
local stdio = require("@lune/stdio")

local game = roblox.deserializePlace(fs.readFile(process.args[1]))
for _, service in game:GetChildren() do
	if service.ClassName == "ServerStorage" then
		for _, child in service:GetChildren() do
			if child.Name == "RHRTruth" and child.ClassName == "StringValue" then
				print(child.Value)
				process.exit(0)
			end
		end
	end
end
stdio.ewrite("no ServerStorage.RHRTruth in this place: run scripts/studio/export_truth.luau in Studio and save again\n")
process.exit(2)
