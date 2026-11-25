-- A library reading its own environment with getfenv() must load (UI Labs does this).
local EnvProbe = require(script.Parent.Parent.Packages.EnvProbe)

return function(target)
	local label = Instance.new("TextLabel")
	label.Name = "Probe"
	label.Size = UDim2.fromOffset(200, 40)
	label.Text = if EnvProbe.injection() == nil and not EnvProbe.reachesLune() then "plain" else "unexpected"
	label.Parent = target
	return function()
		label:Destroy()
	end
end
