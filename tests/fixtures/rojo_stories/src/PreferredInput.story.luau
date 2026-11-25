-- UserInputService.PreferredInput must be readable (a UI that picks glyphs by input family reads it).
local UserInputService = game:GetService("UserInputService")

return function(target)
	local label = Instance.new("TextLabel")
	label.Name = "Probe"
	label.Size = UDim2.fromOffset(200, 40)
	local ok, value = pcall(function()
		return UserInputService.PreferredInput
	end)
	label.Text = if ok and value == Enum.PreferredInput.KeyboardAndMouse and typeof(game) == "Instance"
			and UserInputService.KeyboardEnabled and game:GetService("Players") ~= nil
		then "keyboard"
		else "wrong: " .. tostring(value)
	label.Parent = target
	return function()
		label:Destroy()
	end
end
