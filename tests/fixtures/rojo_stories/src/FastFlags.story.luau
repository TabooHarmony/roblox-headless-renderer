-- React-Lua's SafeFlags calls game:DefineFastFlag in a pcall and reads the error as a string.
local FastFlags = require(script.Parent.Parent.Packages.FastFlags)

return function(target)
	local label = Instance.new("TextLabel")
	label.Name = "Probe"
	label.Size = UDim2.fromOffset(200, 40)
	label.Text = FastFlags.probe()
	label.Parent = target
	return function()
		label:Destroy()
	end
end
