-- The fast-flag probe React-Lua's SafeFlags runs when it loads: define the flag inside a pcall and
-- match the error text. A story must reach the fallback (the Roblox-style string error) instead of
-- crashing on an error value that has no :match.
local FastFlags = {}

function FastFlags.probe(): string
	for _, call in {
		function() game:DefineFastFlag("RhrFixtureFlag", false) end,
		function() game:DefineFastInt("RhrFixtureInt", 1) end,
		function() game:DefineFastString("RhrFixtureString", "") end,
		function() return game:GetFastFlag("RhrFixtureFlag") end,
	} do
		local ok, problem = pcall(call)
		if not ok and not problem:match("The current thread cannot call") then
			return "unexpected: " .. tostring(problem)
		end
	end
	return "fallback"
end

return FastFlags
