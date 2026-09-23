-- tests/studio_cleanup.luau
-- Remove the stray ScreenGui an earlier probe created in the human's open place,
-- so the place is back to its loaded state and can be discarded without saving.
local StarterGui = game:GetService("StarterGui")

local removed = {}
for _, c in ipairs(StarterGui:GetChildren()) do
	if c.Name == "RHRCapture" then
		table.insert(removed, c.ClassName .. ":" .. c.Name)
		c:Destroy()
	end
end

local remaining = {}
for _, c in ipairs(StarterGui:GetChildren()) do
	table.insert(remaining, c.ClassName .. ":" .. c.Name)
end

print("removed=" .. tostring(#removed) .. " starterGui=" .. table.concat(remaining, ","))
return { removed = removed, remaining = remaining }