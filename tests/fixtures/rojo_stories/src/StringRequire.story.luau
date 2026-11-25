-- Luau string requires, resolved inside the project (Ripple uses them).
local StringReq = require(script.Parent.Parent.Packages.StringReq)

return function(target)
	local label = Instance.new("TextLabel")
	label.Name = "Probe"
	label.Size = UDim2.fromOffset(200, 40)
	label.Text = if StringReq.sibling then StringReq.text else "wrong"
	label.Parent = target
	local escape = Instance.new("TextLabel")
	escape.Name = "Escape"
	escape.Size = UDim2.fromOffset(200, 40)
	escape.Text = if pcall(require, "../../../../etc/passwd") then "reached" else "refused"
	escape.Parent = target
	return function()
		label:Destroy()
		escape:Destroy()
	end
end
