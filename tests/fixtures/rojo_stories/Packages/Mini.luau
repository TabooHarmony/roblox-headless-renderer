-- A tiny declarative UI helper standing in for a UI library in the tests: like React
-- or Fusion, it ends in Instance.new, property sets, parenting and event connections.
local Mini = {}

function Mini.create(className: string, props: { [any]: any }, children: { Instance }?)
	local instance = Instance.new(className)
	for key, value in props do
		if key == "Parent" then
			continue
		elseif type(key) == "string" and string.sub(key, 1, 2) == "On" then
			instance[string.sub(key, 3)]:Connect(value)
		else
			instance[key] = value
		end
	end
	for _, child in children or {} do
		child.Parent = instance
	end
	if props.Parent then
		instance.Parent = props.Parent
	end
	return instance
end

return Mini
