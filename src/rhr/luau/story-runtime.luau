-- Run one UI story headlessly and save the UI it builds (rhr.story).
--
--   lune run story-runtime.luau <built.rbxl|rbxm> <module path JSON> <out.rbxm> <width> <height> <name>
--
-- The built file is the Rojo project; the module path (a JSON list of names from the
-- root) is the story's ModuleScript in it. Every UI library ends in the same calls
-- (Instance.new, set properties, parent), so this copies the Roblox side, not any
-- library: Lune's own instances (properties, datatypes, Enums, saving), plus events,
-- the services UI code touches, instance-based require, and a frame loop that lets
-- the UI settle. Story forms: function(target) (Hoarcekat, UI Labs); UI Labs tables
-- with react/reactRoblox, roact, fusion, vide or a generic render; Flipbook's table.
-- Scripts' own threads are left behind: the process exits once the UI is saved.
local roblox = require("@lune/roblox")
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local process = require("@lune/process")
local serde = require("@lune/serde")
local stdio = require("@lune/stdio")
local task = require("@lune/task")

local builtPath, modulePathJson, outPath = process.args[1], process.args[2], process.args[3]
local viewport = roblox.Vector2.new(tonumber(process.args[4]) or 1615, tonumber(process.args[5]) or 1080)
local storyName = process.args[6] or "Story"

local function fail(message)
	stdio.ewrite(tostring(message) .. "\n")
	process.exit(1)
end

-- Signals ---------------------------------------------------------------------------
-- Library code checks typeof(x) == "RBXScriptSignal": the sandbox's typeof reads __type.
local Signal = { __type = "RBXScriptSignal" }
Signal.__index = Signal
local Connection = { __type = "RBXScriptConnection" }
Connection.__index = Connection

function Signal.new()
	return setmetatable({ handlers = {} }, Signal)
end
function Signal:Connect(fn)
	local connection = setmetatable({ Connected = true }, Connection)
	local handlers = self.handlers
	handlers[connection] = fn
	function connection.Disconnect()
		connection.Connected = false
		handlers[connection] = nil
	end
	connection.disconnect = connection.Disconnect
	return connection
end
Signal.connect = Signal.Connect
function Signal:Once(fn)
	local connection
	connection = self:Connect(function(...)
		connection.Disconnect()
		fn(...)
	end)
	return connection
end
function Signal:Fire(...)
	for _, fn in self.handlers do
		task.spawn(fn, ...)
	end
end
function Signal:Wait()
	local thread = coroutine.running()
	self:Once(function(...)
		task.spawn(thread, ...)
	end)
	return coroutine.yield()
end

local signals = setmetatable({}, { __mode = "k" })
local function eventOf(instance, key)
	local byKey = signals[instance]
	if not byKey then
		byKey = {}
		signals[instance] = byKey
	end
	local signal = byKey[key]
	if not signal then
		signal = Signal.new()
		byKey[key] = signal
	end
	return signal
end

local EVENTS = {
	Instance = { "Changed", "ChildAdded", "ChildRemoved", "DescendantAdded", "DescendantRemoving",
		"AncestryChanged", "Destroying", "AttributeChanged" },
	GuiObject = { "InputBegan", "InputEnded", "InputChanged", "MouseEnter", "MouseLeave", "MouseMoved",
		"MouseWheelForward", "MouseWheelBackward", "TouchTap", "TouchLongPress", "TouchPan", "TouchPinch",
		"TouchRotate", "TouchSwipe", "SelectionGained", "SelectionLost", "SelectionChanged" },
	GuiButton = { "Activated", "MouseButton1Click", "MouseButton1Down", "MouseButton1Up", "MouseButton2Click",
		"MouseButton2Down", "MouseButton2Up" },
	TextBox = { "FocusLost", "Focused", "ReturnPressedFromOnScreenKeyboard" },
	RunService = { "Heartbeat", "RenderStepped", "Stepped", "PreRender", "PreAnimation", "PreSimulation",
		"PostSimulation" },
	UserInputService = { "InputBegan", "InputEnded", "InputChanged", "LastInputTypeChanged", "TouchStarted",
		"TouchEnded", "TouchMoved", "WindowFocused", "WindowFocusReleased", "JumpRequest", "GamepadConnected",
		"GamepadDisconnected" },
	Players = { "PlayerAdded", "PlayerRemoving" },
	Player = { "CharacterAdded", "CharacterRemoving", "Chatted" },
	GuiService = { "MenuOpened", "MenuClosed" },
	BindableEvent = { "Event" },
	RemoteEvent = { "OnClientEvent", "OnServerEvent" },
}
for className, names in EVENTS do
	for _, name in names do
		pcall(roblox.implementProperty, className, name, function(instance)
			return eventOf(instance, name)
		end)
	end
end
roblox.implementMethod("Instance", "GetPropertyChangedSignal", function(instance, property)
	return eventOf(instance, "property:" .. property)
end)
roblox.implementMethod("Instance", "GetAttributeChangedSignal", function(instance, attribute)
	return eventOf(instance, "attribute:" .. attribute)
end)
roblox.implementMethod("Instance", "WaitForChild", function(instance, name)
	return instance:FindFirstChild(name)
end)
roblox.implementMethod("BindableEvent", "Fire", function(instance, ...)
	eventOf(instance, "Event"):Fire(...)
end)
roblox.implementMethod("RemoteEvent", "FireServer", function() end)
roblox.implementMethod("RemoteFunction", "InvokeServer", function()
	return nil
end)
for name, value in { IsClient = true, IsServer = false, IsStudio = true, IsRunning = true, IsEdit = false,
	IsRunMode = false } do
	roblox.implementMethod("RunService", name, function()
		return value
	end)
end
local renderSteps = {}
roblox.implementMethod("RunService", "BindToRenderStep", function(_, name, _priority, fn)
	renderSteps[name] = fn
end)
roblox.implementMethod("RunService", "UnbindFromRenderStep", function(_, name)
	renderSteps[name] = nil
end)
for name, value in { TouchEnabled = false, KeyboardEnabled = true, MouseEnabled = true, GamepadEnabled = false } do
	pcall(roblox.implementProperty, "UserInputService", name, function()
		return value
	end)
end
roblox.implementMethod("UserInputService", "GetLastInputType", function()
	return roblox.Enum.UserInputType.MouseButton1
end)
roblox.implementMethod("UserInputService", "GetMouseLocation", function()
	return roblox.Vector2.new(0, 0)
end)
roblox.implementMethod("GuiService", "GetGuiInset", function()
	return roblox.Vector2.new(0, 0), roblox.Vector2.new(0, 0)
end)
roblox.implementMethod("Players", "GetPlayers", function(players)
	return players:GetChildren()
end)

-- Tweens finish at once: a still picture shows where they end.
local TweenInfo = roblox.TweenInfo
	or {
		new = function(time, style, direction, repeats, reverses, delay)
			return { Time = time or 1, EasingStyle = style, EasingDirection = direction, RepeatCount = repeats or 0,
				Reverses = reverses or false, DelayTime = delay or 0 }
		end,
	}
roblox.implementMethod("TweenService", "Create", function(_, instance, _info, goals)
	local tween = { Completed = Signal.new(), PlaybackState = roblox.Enum.PlaybackState.Begin }
	function tween.Play()
		for property, value in goals do
			instance[property] = value
		end
		tween.PlaybackState = roblox.Enum.PlaybackState.Completed
		tween.Completed:Fire(roblox.Enum.PlaybackState.Completed)
	end
	return setmetatable(tween, {
		__index = function()
			return function() end
		end,
	})
end)
roblox.implementMethod("TweenService", "GetValue", function(_, alpha)
	return alpha
end)
-- Text measures: a rough width (RHR's own text engine lays the text out afterwards).
roblox.implementMethod("TextService", "GetTextSize", function(_, text, size)
	return roblox.Vector2.new(#tostring(text) * size * 0.5, size)
end)
local guids = 0
roblox.implementMethod("HttpService", "GenerateGUID", function(_, braces)
	guids += 1
	local id = string.format("%08X-0000-4000-8000-%012X", guids, guids)
	return if braces == false then id else "{" .. id .. "}"
end)
roblox.implementMethod("HttpService", "JSONEncode", function(_, value)
	return serde.encode("json", value)
end)
roblox.implementMethod("HttpService", "JSONDecode", function(_, text)
	return serde.decode("json", text)
end)

-- Sizes RHR works out after the story ran: read as zero while it runs, not an error.
local ZERO = roblox.Vector2.new(0, 0)
local function presetSizes(instance)
	if instance:IsA("GuiBase2d") then
		pcall(function()
			instance.AbsoluteSize = ZERO
			instance.AbsolutePosition = ZERO
		end)
	end
end

-- The data model ------------------------------------------------------------------------
local ok, game = pcall(function()
	local data = fs.readFile(builtPath)
	if string.sub(builtPath, -5) == ".rbxl" or string.sub(builtPath, -6) == ".rbxlx" then
		return roblox.deserializePlace(data)
	end
	local model = roblox.Instance.new("DataModel")
	local holder = model:GetService("ReplicatedStorage")
	for _, root in roblox.deserializeModel(data) do
		root.Parent = holder
	end
	return model
end)
if not ok then
	fail("could not read the built project: " .. tostring(game))
end
for _, instance in game:GetDescendants() do
	presetSizes(instance)
end
local workspace = game:GetService("Workspace")
local camera = workspace.CurrentCamera or roblox.Instance.new("Camera")
camera.Parent = workspace
workspace.CurrentCamera = camera
pcall(function()
	camera.ViewportSize = viewport
end)
local players = game:GetService("Players")
local localPlayer = players:FindFirstChildOfClass("Player") or roblox.Instance.new("Player")
localPlayer.Name = if localPlayer.Name == "Player" or localPlayer.Name == "" then "Player" else localPlayer.Name
localPlayer.Parent = players
pcall(roblox.implementProperty, "Players", "LocalPlayer", function()
	return localPlayer
end)
pcall(function()
	players.LocalPlayer = localPlayer
end)
local playerGui = localPlayer:FindFirstChildOfClass("PlayerGui") or roblox.Instance.new("PlayerGui")
playerGui.Parent = localPlayer

-- Modules -------------------------------------------------------------------------------
local loaded, loading = {}, {}
local base

local function requireModule(target, from)
	if typeof(target) ~= "Instance" then
		error(`require({typeof(target)}) is not supported when running a story (only ModuleScripts in the project)`, 3)
	end
	if not target:IsA("ModuleScript") then
		error(`{target:GetFullName()} is not a ModuleScript`, 3)
	end
	if loaded[target] ~= nil then
		return loaded[target]
	end
	if loading[target] then
		error(`require loop at {target:GetFullName()}`, 3)
	end
	loading[target] = true
	local environment = table.clone(base) -- (copied: Lune's load() sets its own metatable)
	environment.script = target
	environment.require = function(module)
		return requireModule(module, target)
	end
	local chunk = luau.load(target.Source, { debugName = target:GetFullName(), environment = environment })
	local result = chunk()
	loading[target] = nil
	loaded[target] = if result == nil then true else result
	return result
end

local nativeTypeof = typeof
base = {
	game = game,
	Game = game,
	workspace = workspace,
	Workspace = workspace,
	shared = {},
	Instance = {
		new = function(className, parent)
			local instance = roblox.Instance.new(className)
			presetSizes(instance)
			if parent then
				instance.Parent = parent
			end
			return instance
		end,
	},
	Enum = roblox.Enum,
	TweenInfo = TweenInfo,
	task = task,
	wait = task.wait,
	delay = task.delay,
	spawn = task.spawn,
	tick = os.clock,
	time = os.clock,
	elapsedTime = os.clock,
	settings = function()
		return {}
	end,
	UserSettings = function()
		return { GetService = function() return {} end }
	end,
	warn = function(...)
		stdio.ewrite("[warn] " .. table.concat(table.pack(...) :: any, " ") .. "\n")
	end,
	print = function() end, -- a story's prints are noise in a render
	-- The way from a story's globals to Lune's own (getfenv(0).require reaches
	-- @lune/process). Not a sandbox: a story still runs with Lune's powers in reach;
	-- the docs say not to run untrusted ones.
	getfenv = function()
		error("getfenv is not available when running a story", 2)
	end,
	setfenv = function()
		error("setfenv is not available when running a story", 2)
	end,
	typeof = function(value)
		if type(value) == "table" then
			local meta = getmetatable(value)
			if type(meta) == "table" and type(rawget(meta, "__type")) == "string" then
				return meta.__type
			end
		end
		return nativeTypeof(value)
	end,
}
for _, name in { "UDim", "UDim2", "Vector2", "Vector3", "Vector2int16", "Vector3int16", "Color3", "ColorSequence",
	"ColorSequenceKeypoint", "NumberSequence", "NumberSequenceKeypoint", "NumberRange", "Rect", "CFrame",
	"BrickColor", "Font", "Faces", "Axes", "Ray", "Region3", "PhysicalProperties", "Random", "DateTime",
	"Content", "OverlapParams", "RaycastParams" } do
	if roblox[name] ~= nil then
		base[name] = roblox[name]
	end
end

-- Run -----------------------------------------------------------------------------------
local storyScript = game
for _, name in serde.decode("json", modulePathJson) do
	local child = storyScript:FindFirstChild(name)
	if not child then
		fail(`the story's module {name} was not found under {storyScript:GetFullName()} in the built project`)
	end
	storyScript = child
end

local screen = roblox.Instance.new("ScreenGui")
screen.Name = storyName
screen.IgnoreGuiInset = true
screen.ResetOnSpawn = false
screen.Parent = playerGui
local target = roblox.Instance.new("Frame")
target.Name = "Target"
target.Size = roblox.UDim2.fromScale(1, 1)
target.BackgroundTransparency = 1
target.Parent = screen
pcall(function()
	screen.AbsoluteSize = viewport
	target.AbsoluteSize = viewport
end)

local runService = game:GetService("RunService")
local function frames(count)
	for _ = 1, count do
		for _, fn in renderSteps do
			task.spawn(fn, 1 / 60)
		end
		runService.RenderStepped:Fire(1 / 60)
		runService.PreRender:Fire(1 / 60)
		runService.Heartbeat:Fire(1 / 60)
		task.wait()
	end
end

local function controlDefaults(controls)
	local values = {}
	for name, control in controls or {} do
		if type(control) == "table" then
			local value = control.ControlValue
			if value == nil then value = control.Default end
			if value == nil then value = control.default end
			if value == nil then value = control.__default end
			if value == nil and type(control.List) == "table" then value = control.List[1] end
			values[name] = value
		else
			values[name] = control
		end
	end
	return values
end

local function mount()
	local story = requireModule(storyScript)
	if type(story) == "function" then
		return story(target)
	end
	if type(story) ~= "table" then
		error("a story module returns a function(target) or a story table; this one returned a " .. typeof(story))
	end
	local controls = controlDefaults(story.controls)
	local props = { target = target, controls = controls, converted = {}, subscribe = function()
		return function() end
	end }
	if story.react and story.reactRoblox then
		local React, ReactRoblox = story.react, story.reactRoblox
		local element = story.story
		if type(element) == "function" then
			element = React.createElement(element, props)
		end
		local root = if story.renderer == "legacy" and ReactRoblox.createLegacyRoot
			then ReactRoblox.createLegacyRoot(target)
			else ReactRoblox.createRoot(target)
		root:render(element)
		return
	end
	if story.roact then
		local Roact = story.roact
		local element = story.story
		if type(element) == "function" then
			element = Roact.createElement(element, props)
		end
		Roact.mount(element, target)
		return
	end
	if story.vide then
		story.vide.mount(function()
			return story.story(props)
		end, target)
		return
	end
	if type(story.render) == "function" then
		return story.render(props)
	end
	if story.fusion and type(story.story) == "function" then
		props.scope = story.fusion.scoped and story.fusion.scoped(story.fusion)
		return story.story(props)
	end
	if type(story.story) == "function" then
		return story.story(target, props)
	end
	error("a story table needs react + reactRoblox, roact, vide, fusion, a render function or a story function")
end

local okMount, problem = xpcall(mount, function(err)
	return tostring(err) .. "\n" .. debug.traceback("", 2)
end)
if not okMount then
	fail(problem)
end
frames(30)

-- Lune keeps a legacy `Font = Enum.Font.X` as an EnumItem it cannot save: as a FontFace.
for _, instance in screen:GetDescendants() do
	if instance:IsA("TextLabel") or instance:IsA("TextButton") or instance:IsA("TextBox") then
		local okFont, legacy = pcall(function()
			return instance.Font -- (reading it fails unless a story set it)
		end)
		if okFont and nativeTypeof(legacy) == "EnumItem" then
			instance.FontFace = roblox.Font.fromEnum(legacy)
		end
	end
end
local okSave, saveProblem = pcall(function()
	fs.writeFile(outPath, roblox.serializeModel({ screen }))
end)
if not okSave then
	fail("could not save the UI the story built: " .. tostring(saveProblem))
end
print(`ok {#screen:GetDescendants()}`)
process.exit(0)
