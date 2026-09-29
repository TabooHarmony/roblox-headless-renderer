-- Table form with a generic render (UI Labs), and controls: a plain default and a
-- control object with its value in ControlValue.
local Mini = require(script.Parent.Parent.Packages.Mini)

return {
	controls = {
		Title = "Settings",
		Rows = { EntryType = "Control", Type = "Slider", ControlValue = 3 },
	},
	render = function(props)
		local panel = Mini.create("Frame", {
			Name = "Panel",
			Size = UDim2.fromOffset(300, 60 + props.controls.Rows * 40),
			BackgroundColor3 = Color3.fromRGB(30, 30, 36),
			Parent = props.target,
		}, {
			Mini.create("TextLabel", { Name = "Title", Size = UDim2.new(1, 0, 0, 40), Text = props.controls.Title,
				TextColor3 = Color3.new(1, 1, 1), BackgroundTransparency = 1 }),
		})
		for row = 1, props.controls.Rows do
			Mini.create("TextButton", { Name = "Row" .. row, Position = UDim2.fromOffset(10, 20 + row * 40),
				Size = UDim2.new(1, -20, 0, 32), Text = "Option " .. row, OnActivated = function() end, Parent = panel })
		end
		return function()
			panel:Destroy()
		end
	end,
}
