-- Animation a story starts on RunService / task time must have run before the UI is saved:
-- a panel that slides in on Heartbeat steps, one that waits, one that is delayed, one on a clock.
local RunService = game:GetService("RunService")

local function box(target, name, y)
	local frame = Instance.new("Frame")
	frame.Name = name
	frame.Size = UDim2.fromOffset(100, 20)
	frame.Position = UDim2.fromOffset(0, y)
	frame.Parent = target
	return frame
end

return function(target)
	-- Slides in from x = 2000 to 0 at 1000 px/s, driven by the Heartbeat delta (a spring does the same).
	local slide = box(target, "Slide", 0)
	local x = 2000
	slide.Position = UDim2.fromOffset(x, 0)
	local connection
	connection = RunService.Heartbeat:Connect(function(dt)
		x = math.max(0, x - 1000 * dt)
		slide.Position = UDim2.fromOffset(x, 0)
		if x == 0 then
			connection:Disconnect()
		end
	end)

	-- A render-step loop and the RenderStepped / Stepped signals.
	local render = box(target, "Render", 30)
	local rendered = 0
	RunService.RenderStepped:Connect(function(dt)
		rendered += dt
		render.Size = UDim2.fromOffset(math.floor(rendered * 100 + 0.5), 20)
	end)
	local stepped = box(target, "Stepped", 60)
	RunService.Stepped:Connect(function(_, dt)
		stepped.Size = UDim2.fromOffset(math.floor(dt * 6000 + 0.5), 20)
	end)

	-- task.wait and task.delay run on game time (0.5 s, then 1 s later), not real time.
	local waited = box(target, "Waited", 90)
	task.spawn(function()
		local elapsed = task.wait(0.5)
		waited.Size = UDim2.fromOffset(math.floor(elapsed * 100 + 0.5), 20)
	end)
	local delayed = box(target, "Delayed", 120)
	task.delay(1, function()
		delayed.Size = UDim2.fromOffset(300, 20)
	end)

	-- Clocks advance between frames.
	local clock = box(target, "Clock", 150)
	local started = os.clock()
	local startedTick = tick()
	RunService.Heartbeat:Connect(function()
		clock.Size = UDim2.fromOffset(math.floor((os.clock() - started) * 100 + 0.5) + math.floor((tick() - startedTick) * 100 + 0.5), 20)
	end)

	-- The story function itself may wait: it sleeps in game time while the frames run.
	task.wait(0.25)
	box(target, "Mounted", 180)
end
