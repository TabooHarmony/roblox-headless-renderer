-- Code that sizes itself from the screen: the target's size and the camera's
-- ViewportSize are the viewport RHR draws at (--viewport).
return function(target)
	local screen = target.AbsoluteSize
	local camera = workspace.CurrentCamera.ViewportSize
	local bar = Instance.new("Frame")
	bar.Name = "Bar"
	bar.Size = UDim2.fromOffset(screen.X // 2, 20)
	bar.Parent = target
	local label = Instance.new("TextLabel")
	label.Name = "Size"
	label.Position = UDim2.fromOffset(0, 40)
	label.Size = UDim2.fromOffset(200, 30)
	label.Text = `{camera.X}x{camera.Y}`
	label.Parent = target
	return function()
		bar:Destroy()
		label:Destroy()
	end
end
