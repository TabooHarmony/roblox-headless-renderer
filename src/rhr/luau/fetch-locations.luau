-- Ask Roblox where to download assets, as the user signed in to Roblox Studio here.
--
--   lune run fetch-locations.luau < ids.json
--
-- stdin is a JSON array of asset ids (strings). Studio's saved login is read here
-- (Lune's roblox.getAuthCookie) and sent only to Roblox's asset delivery batch
-- endpoint, the same service Studio asks. It is never printed, written or handed back
-- to RHR. What is printed is one JSON object, id -> {location} or {code, message}:
-- a location is a short-lived signed link on Roblox's CDN for that one file, not the
-- login. Prints "nologin" when there is no saved login.
local net = require("@lune/net")
local process = require("@lune/process")
local roblox = require("@lune/roblox")
local serde = require("@lune/serde")
local stdio = require("@lune/stdio")
local task = require("@lune/task")

local BATCH = 256 -- the endpoint refuses more assets per request

local ok, cookie = pcall(roblox.getAuthCookie)
if not ok or not cookie or #cookie == 0 then
	print("nologin")
	process.exit(3)
end

local ids = serde.decode("json", stdio.readToEnd())
local results = {}
local pending = 0

local function ask(chunk)
	local body = {}
	for _, id in chunk do
		table.insert(body, { assetId = tonumber(id), requestId = id })
	end
	local okRequest, response = pcall(net.request, {
		url = "https://assetdelivery.roblox.com/v2/assets/batch",
		method = "POST",
		headers = {
			Cookie = cookie,
			["User-Agent"] = "roblox-headless-renderer",
			["Content-Type"] = "application/json",
		},
		body = serde.encode("json", body),
	})
	if not okRequest then
		for _, id in chunk do
			results[id] = { code = 0, message = "request failed" }
		end
	elseif not response.ok then
		for _, id in chunk do
			results[id] = { code = response.statusCode, message = "batch refused" }
		end
	else
		for _, item in serde.decode("json", response.body) do
			local locations = item.locations
			if locations and locations[1] and locations[1].location then
				results[item.requestId] = { location = locations[1].location }
			else
				local err = item.errors and item.errors[1] or {}
				results[item.requestId] = { code = err.code or 0, message = err.message or "no location" }
			end
		end
	end
	pending -= 1
end

for start = 1, #ids, BATCH do
	pending += 1
	task.spawn(ask, table.move(ids, start, math.min(start + BATCH - 1, #ids), 1, {}))
end
while pending > 0 do
	task.wait()
end
print(serde.encode("json", results))
