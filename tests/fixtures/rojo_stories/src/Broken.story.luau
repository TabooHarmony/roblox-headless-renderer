local Mini = require(script.Parent.Parent.Packages.Mini)

return function(target)
	local frame = Mini.create("Frame", { Parent = target })
	frame.NotAProperty.Oops = 1
end
