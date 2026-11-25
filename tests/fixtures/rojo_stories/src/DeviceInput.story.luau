-- A story sees the input of the --device it is drawn for: touch on a phone or tablet, a gamepad on the
-- console, keyboard and mouse otherwise. A UI that reads it (as layouts do) draws its touch variant.
local UserInputService = game:GetService("UserInputService")

return function(target)
	local kind = if UserInputService.PreferredInput == Enum.PreferredInput.Touch and UserInputService.TouchEnabled
			and not UserInputService.KeyboardEnabled and not UserInputService.MouseEnabled
			and UserInputService:GetLastInputType() == Enum.UserInputType.Touch
		then "touch"
		elseif UserInputService.PreferredInput == Enum.PreferredInput.Gamepad and UserInputService.GamepadEnabled
			and not UserInputService.TouchEnabled and UserInputService:GetLastInputType() == Enum.UserInputType.Gamepad1
		then "gamepad"
		elseif UserInputService.PreferredInput == Enum.PreferredInput.KeyboardAndMouse and UserInputService.KeyboardEnabled
			and UserInputService.MouseEnabled and not UserInputService.TouchEnabled
		then "keyboard"
		else "mixed"
	local label = Instance.new("TextLabel")
	label.Name = "Probe"
	label.Size = UDim2.fromOffset(200, 40)
	label.Text = kind
	label.Parent = target
	-- The touch variant has big buttons; the keyboard variant a small one (a touch finding on it).
	local button = Instance.new("TextButton")
	button.Name = "Action"
	button.Position = UDim2.fromOffset(0, 60)
	button.Size = if kind == "touch" then UDim2.fromOffset(200, 60) else UDim2.fromOffset(30, 20)
	button.Text = "Go"
	button.Parent = target
end
