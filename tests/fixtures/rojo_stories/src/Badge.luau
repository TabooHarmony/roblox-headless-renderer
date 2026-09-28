local Mini = require(script.Parent.Parent.Packages.Mini)

return function(props)
	return Mini.create("Frame", {
		Name = props.name,
		Size = UDim2.fromOffset(200, 80),
		Position = UDim2.fromOffset(40, 40),
		BackgroundColor3 = Color3.fromRGB(40, 120, 220),
	}, {
		Mini.create("UICorner", { CornerRadius = UDim.new(0, 12) }),
		Mini.create("TextLabel", {
			Name = "Title",
			Size = UDim2.fromScale(1, 1),
			BackgroundTransparency = 1,
			Text = props.text,
			TextColor3 = Color3.new(1, 1, 1),
			TextSize = 24,
			Font = Enum.Font.GothamBold,
		}),
	})
end
