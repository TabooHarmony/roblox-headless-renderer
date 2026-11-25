-- Engine properties Lune has no value for must read as sensible defaults (UI code reads them freely).
local GuiService = game:GetService("GuiService")
local UserInputService = game:GetService("UserInputService")

return function(target)
	local inset = GuiService.TopbarInset
	local results = {
		inset = inset.Max.X == 800 and inset.Height == 58, -- a Rect across the screen, rhr's top-bar height
		input = UserInputService.PreferredInput == Enum.PreferredInput.KeyboardAndMouse,
		flags = UserInputService.KeyboardEnabled and not UserInputService.TouchEnabled,
		neutral = GuiService.IsModalDialog == false, -- not in the table: a typed neutral value
		real = GuiService.SelectedObject == nil and UserInputService:GetLastInputType() ~= nil, -- untouched
		kind = typeof(game) == "Instance" and typeof(UserInputService) == "Instance",
		same = game:GetService("GuiService") == GuiService,
	}
	local failed = {}
	for name, ok in results do
		if not ok then
			table.insert(failed, name)
		end
	end
	table.sort(failed)
	local label = Instance.new("TextLabel")
	label.Name = "Probe"
	label.Size = UDim2.fromOffset(200, 40)
	label.Text = if #failed == 0 then "defaults" else "wrong: " .. table.concat(failed, ",")
	label.Parent = target
	return function()
		label:Destroy()
	end
end
