-- Engine methods UI code calls freely must answer neutral values, not "is not a valid member".
local Players = game:GetService("Players")
local GuiService = game:GetService("GuiService")
local UserInputService = game:GetService("UserInputService")
local TextService = game:GetService("TextService")
local ContentProvider = game:GetService("ContentProvider")
local MarketplaceService = game:GetService("MarketplaceService")
local PolicyService = game:GetService("PolicyService")
local StarterGui = game:GetService("StarterGui")

return function(target)
	local player = Players.LocalPlayer
	local frame = Instance.new("Frame")
	frame.Size = UDim2.fromOffset(10, 10)
	frame.Parent = target
	local preloaded = 0
	ContentProvider:PreloadAsync({ frame }, function()
		preloaded += 1
	end)
	local tweened = false
	frame:TweenPosition(UDim2.fromOffset(50, 60), Enum.EasingDirection.Out, Enum.EasingStyle.Quad, 0.3, true, function(status)
		tweened = status == Enum.TweenStatus.Completed
	end)
	local policy = PolicyService:GetPolicyInfoForPlayerAsync(player)
	local results = {
		loaded = game:IsLoaded(),
		serverTime = typeof(workspace:GetServerTimeNow()) == "number"
			and workspace:GetServerTimeNow() == game:GetService("Workspace"):GetServerTimeNow(),
		guiInset = typeof(GuiService:GetGuiInset()) == "Vector2" and GuiService:IsTenFootInterface() == false,
		textSize = typeof(TextService:GetTextSize("Hi", 20, Enum.Font.SourceSans, Vector2.new(100, 100))) == "Vector2",
		filter = TextService:FilterStringAsync("Hi", player.UserId):GetNonChatStringForBroadcastAsync() == "Hi",
		input = UserInputService:GetPlatform() == Enum.Platform.Windows and UserInputService:GetLastInputType() ~= nil
			and UserInputService:IsKeyDown(Enum.KeyCode.W) == false and UserInputService:GetFocusedTextBox() == nil,
		preload = preloaded == 1,
		owns = MarketplaceService:UserOwnsGamePassAsync(player.UserId, 1) == false,
		product = typeof(MarketplaceService:GetProductInfo(1).Name) == "string",
		policy = policy.ArePaidRandomItemsRestricted == false and policy.IsPaidItemTradingAllowed == true,
		player = typeof(player.UserId) == "number" and typeof(player.DisplayName) == "string"
			and Players:GetPlayerByUserId(player.UserId) == player and player:IsInGroup(1) == false,
		tween = tweened and frame.Position == UDim2.fromOffset(50, 60),
		noops = pcall(function()
			MarketplaceService:PromptGamePassPurchase(player, 1)
			StarterGui:SetCoreGuiEnabled(Enum.CoreGuiType.Chat, false)
			game:GetService("Debris"):AddItem(frame, 1)
		end),
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
	label.Text = if #failed == 0 then "methods" else "wrong: " .. table.concat(failed, ",")
	label.Parent = target
end
