-- Download Roblox assets as the user signed in to Roblox Studio on this machine.
--
--   lune run fetch-signed-in.luau <out-dir> <asset-id> [<asset-id> ...]
--
-- Used only by `rhr fetch --use-studio-login`. Studio's saved login is read here
-- (Lune's roblox.getAuthCookie) and sent only to Roblox's own asset delivery
-- service, the same request Studio makes to show the asset. It is never printed,
-- written or handed back to RHR: this script writes <out-dir>/<id>.bin for each
-- asset it gets and prints one status line per id.
local fs = require("@lune/fs")
local net = require("@lune/net")
local process = require("@lune/process")
local roblox = require("@lune/roblox")

local out = process.args[1]
if not out then
	print("usage: lune run fetch-signed-in.luau <out-dir> <asset-id> ...")
	process.exit(2)
end

local ok, cookie = pcall(roblox.getAuthCookie)
if not ok or not cookie or #cookie == 0 then
	print("nologin")
	process.exit(3)
end

for index = 2, #process.args do
	local id = process.args[index]
	if not string.match(id, "^%d+$") then
		print(id .. " invalid")
		continue
	end
	local okRequest, response = pcall(net.request, {
		url = "https://assetdelivery.roblox.com/v1/asset/?id=" .. id,
		headers = { Cookie = cookie, ["User-Agent"] = "roblox-headless-renderer" },
	})
	if not okRequest then
		print(id .. " error")
	elseif response.ok then
		fs.writeFile(out .. "/" .. id .. ".bin", response.body)
		print(id .. " ok")
	else
		print(id .. " http " .. tostring(response.statusCode))
	end
end
