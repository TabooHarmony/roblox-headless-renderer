-- Function form (Hoarcekat / UI Labs): mounts into target, returns a cleanup.
local TweenService = game:GetService("TweenService")
local Badge = require(script.Parent.Badge)

return function(target)
	local badge = Badge({ name = "Badge", text = "Level 7" })
	badge.Parent = target
	-- Code that reads sizes at mount, listens for changes and animates in.
	local width = target.AbsoluteSize.X + badge.AbsolutePosition.Y
	badge:GetPropertyChangedSignal("Size"):Connect(function() end)
	local button = Instance.new("TextButton")
	button.Name = "Claim"
	button.Size = UDim2.fromOffset(120, 40)
	button.Position = UDim2.fromOffset(40, 200)
	button.Text = if width >= 0 then "Claim" else "?"
	button.Activated:Connect(function() end)
	button.Parent = target
	TweenService:Create(badge, TweenInfo.new(0.5), { Position = UDim2.fromOffset(300, 40) }):Play()
	return function()
		badge:Destroy()
	end
end
