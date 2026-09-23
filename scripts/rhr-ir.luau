local roblox = require("@lune/roblox")
local fs = require("@lune/fs")
local serde = require("@lune/serde")
local process = require("@lune/process")

-- IR emitter. Dumps a Roblox model/place to JSON with real datatypes, so the
-- Python side never has to guess an enum's name or drop a property it cannot
-- decode. rbx-dom detects binary vs XML by content, so .rbxm, .rbxmx and .rbxl
-- all go through the same call.
--
-- Note the PROPS allowlist: a property absent from this list is omitted from the
-- IR entirely, which would make a fixture pass for the wrong reason. Keep it a
-- superset of the UI properties under test, and extend it when you add a fixture
-- that reads a property not listed here.
--
-- usage: lune run scripts/rhr-ir.luau <source> <out.json>

local PROPS = {
  -- GuiObject geometry and appearance
  "Size", "Position", "AnchorPoint", "BackgroundColor3", "BackgroundTransparency", "BackgroundColor",
  "BorderColor3", "BorderSizePixel", "BorderMode", "ClipsDescendants", "Visible", "ZIndex", "Rotation",
  "LayoutOrder", "SizeConstraint", "AutomaticSize", "Style", "Active", "Interactable", "Selectable",
  -- GuiBase2d / layer behaviour
  "Name", "Enabled", "DisplayOrder", "IgnoreGuiInset", "ResetOnSpawn", "SafeAreaCompatibility",
  "ClipToDeviceSafeArea", "ScreenInsets", "OnTopOfCoreBlur", "ZIndexBehavior",
  -- Buttons
  "AutoButtonColor", "Modal", "Selected",
  -- Text
  "Text", "TextColor3", "TextSize", "TextScaled", "TextWrapped", "TextTransparency", "TextStrokeColor3",
  "TextStrokeTransparency", "TextXAlignment", "TextYAlignment", "RichText", "LineHeight",
  "MaxVisibleGraphemes", "Font", "FontFace", "TextTruncate", "FontSize",
  "PlaceholderText", "PlaceholderColor3", "ClearTextOnFocus", "MultiLine", "TextEditable",
  -- Images
  "Image", "ImageColor3", "ImageTransparency", "ImageRectOffset", "ImageRectSize", "ScaleType",
  "TileSize", "SliceCenter", "SliceScale", "ResampleMode", "HoverImage", "PressedImage",
  -- ScrollingFrame
  "CanvasSize", "CanvasPosition", "AutomaticCanvasSize", "ScrollBarThickness", "ScrollBarImageColor3",
  "ScrollBarImageTransparency", "ScrollingDirection", "ElasticBehavior", "VerticalScrollBarInset",
  "HorizontalScrollBarInset", "ScrollBarFadeDelay", "SelectionImageObject",
  -- CanvasGroup / layers
  "GroupTransparency", "GroupColor3",
  -- UI modifiers
  -- UICorner stores its radius in four per-corner UDims in current files; the
  -- unified CornerRadius accessor has no default in the Lua bridge's reflection
  -- snapshot and cannot be read at all. Read the four and let the adapter collapse
  -- them (see src/rhr/adapter.py).
  "CornerRadius", "TopLeftRadius", "TopRightRadius", "BottomLeftRadius", "BottomRightRadius",
  "Thickness", "Color", "Transparency", "ApplyStrokeMode", "LineJoinMode",
  "StrokeSizingMode", "BorderStrokePosition", "Gradient", "Offset", "FillDirection",
  "HorizontalAlignment", "VerticalAlignment", "SortOrder", "Padding", "Wraps", "HorizontalFlex",
  "VerticalFlex", "ItemLineAlignment", "FillDirectionMaxCells", "StartCorner", "CellSize",
  "CellPadding", "PaddingTop", "PaddingBottom", "PaddingLeft", "PaddingRight", "AspectRatio",
  "AspectType", "DominantAxis", "Scale", "MinTextSize", "MaxTextSize", "MinSize", "MaxSize",
  "FlexMode", "GrowRatio", "ShrinkRatio", "AspectRatioConstraint",
  -- Geometry and cameras
  "CFrame", "PivotOffset", "WorldPivot", "PrimaryPart", "Position", "Orientation", "Color", "Color3", "Material", "Shape", "shape", "MeshType",
  "MeshId", "TextureID", "FieldOfView", "CameraType", "Focus", "Gravity", "Anchored", "AssemblyLinearVelocity", "CanCollide",
  "CanTouch", "CanQuery", "CastShadow", "Reflectance", "Massless", "Locked",
  -- Local lights
  "Range", "Shadows", "Angle",
  -- Beam / Trail references and static beam geometry
  "Attachment0", "Attachment1", "Width0", "Width1", "WidthScale", "CurveSize0", "CurveSize1", "Segments", "FaceCamera",
  "TextureLength", "TextureMode", "TextureSpeed", "MaxLength", "MinLength",
  -- Viewport / video. CameraCFrame is the ViewportFrame's own camera pose: games
  -- assign CurrentCamera (a Camera instance) at runtime, and the saved place stores
  -- the pose in this property instead. Without it a static fixture renders its 3D
  -- content from the fallback camera and misses the authored framing entirely.
  "Ambient", "OutdoorAmbient", "GlobalShadows", "ClockTime", "GeographicLatitude",
  -- Atmosphere / Sky
  "Density", "Haze", "Glare", "Decay",
  "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp",
  "SkyboxOrientation", "CelestialBodiesShown", "MoonAngularSize", "MoonTextureId",
  "StarCount", "SunAngularSize", "SunTextureId",
  "ShadowSoftness", "EnvironmentDiffuseScale", "EnvironmentSpecularScale", "ExposureCompensation",
  "LightColor", "LightDirection", "LightDirectionLatitude", "LightDirectionLongitude",
  "CameraCFrame", "CameraMode",
  "FieldOfView", "Camera", "Video", "Looped", "Playing", "Volume", "TimePosition", "AutoPlay",
  -- In-world UI
  "Adornee", "AlwaysOnTop", "Brightness", "ClipsDescendants", "ExtentsOffset", "ExtentsOffsetWorldSpace",
  "MaxDistance", "SizeOffset", "StudsOffset", "StudsOffsetWorldSpace", "Face", "SizingMode",
  "CanvasSize", "PixelsPerStud", "ZOffset", "GroupTransparency",
  -- ParticleEmitter
  "Acceleration", "Brightness", "Color", "Drag", "EmissionDirection", "Enabled", "FlipbookBlendFrames",
  "FlipbookFramerate", "FlipbookIncompatible", "FlipbookLayout", "FlipbookMode", "FlipbookSizeX",
  "FlipbookSizeY", "FlipbookStartRandom", "Lifetime", "LightEmission", "LightInfluence",
  "LocalTransparencyModifier", "LockedToPart", "Orientation", "Rate", "Rotation", "RotSpeed",
  "Shape", "ShapeInOut", "ShapePartial", "ShapeStyle", "Size", "Speed", "SpreadAngle", "Squash",
  "Texture", "StudsPerTileU", "StudsPerTileV", "OffsetStudsU", "OffsetStudsV",
  "TimeScale", "Transparency", "VelocityInheritance", "VelocitySpread", "WindAffectsDrag",
  "ZOffset",
  -- Containers. (No "Name" here: it is already listed above, and this is a list, so a
  -- duplicate is a second read of the same property on every instance.)
}

local PROPS_SET = {}
for _, name in ipairs(PROPS) do PROPS_SET[name] = true end

local CONTENT_PROPERTY_ALIASES = {
  MeshId = "MeshContent",
  TextureID = "TextureContent",
  SkyboxBk = "SkyboxBackContent",
  SkyboxDn = "SkyboxDownContent",
  SkyboxFt = "SkyboxFrontContent",
  SkyboxLf = "SkyboxLeftContent",
  SkyboxRt = "SkyboxRightContent",
  SkyboxUp = "SkyboxUpContent",
  MoonTextureId = "MoonTextureContent",
  SunTextureId = "SunTextureContent",
}

local VISUAL_CLASSES = {
  -- 2D UI roots and paintable objects
  ScreenGui = true, SurfaceGui = true, BillboardGui = true,
  Frame = true, CanvasGroup = true, ScrollingFrame = true,
  TextLabel = true, TextButton = true, TextBox = true,
  ImageLabel = true, ImageButton = true, ViewportFrame = true, VideoFrame = true,
  -- UI modifiers/layout
  UICorner = true, UIStroke = true, UIGradient = true, UIPadding = true,
  UIListLayout = true, UIGridLayout = true, UITableLayout = true, UIPageLayout = true,
  UIScale = true, UIAspectRatioConstraint = true, UISizeConstraint = true,
  UITextSizeConstraint = true, UIFlexItem = true,
  -- Static world geometry and authored cameras/lighting
  Part = true, WedgePart = true, CornerWedgePart = true, MeshPart = true,
  UnionOperation = true, SpecialMesh = true, Camera = true, Lighting = true,
  Decal = true, Texture = true, Attachment = true, Bone = true,
  PointLight = true, SpotLight = true, SurfaceLight = true,
  Beam = true, Trail = true, ParticleEmitter = true,
  -- Known visual classes not rendered yet: keep them visible to coverage/fallbacks.
  Terrain = true, Sky = true, Atmosphere = true, SurfaceAppearance = true,
  MaterialVariant = true, Highlight = true,
}

local VISUAL_XML_RECOVERY = {
  BorderSizePixel = true,
  DisplayOrder = true,
}

local function profile_keeps_class(profile, className)
  if not VISUAL_CLASSES[className] then return false end
  if profile == "static" and className == "ParticleEmitter" then return false end
  return true
end

-- JSON has no infinity; UISizeConstraint.MaxSize defaults to (inf, inf). Clamp to
-- a large finite sentinel the adapter reads as "unbounded".
local function finite(n)
  if n ~= n or n == math.huge or n == -math.huge then return 1e6 end
  return n
end

local function conv(v, depth)
  depth = depth or 0
  if v == nil or depth > 5 then return nil end
  local t = typeof(v)
  if t == "Vector2" then return { X = finite(v.X), Y = finite(v.Y), _t = t } end
  if t == "Vector3" then return { X = finite(v.X), Y = finite(v.Y), Z = finite(v.Z), _t = t } end
  if t == "CFrame" then
    local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = v:GetComponents()
    return {
      X = x, Y = y, Z = z,
      R00 = r00, R01 = r01, R02 = r02,
      R10 = r10, R11 = r11, R12 = r12,
      R20 = r20, R21 = r21, R22 = r22,
      _t = t,
    }
  end
  if t == "UDim" then return { Scale = v.Scale, Offset = v.Offset, _t = t } end
  if t == "UDim2" then return { XS = v.X.Scale, XO = v.X.Offset, YS = v.Y.Scale, YO = v.Y.Offset, _t = t } end
  if t == "Color3" then return { R = v.R, G = v.G, B = v.B, _t = t } end
  if t == "Rect" then return { Min = conv(v.Min, depth + 1), Max = conv(v.Max, depth + 1), _t = t } end
  if t == "NumberRange" then return { Min = v.Min, Max = v.Max, _t = t } end
  if t == "EnumItem" then return { enum = tostring(v.EnumType), name = v.Name, value = v.Value, _t = t } end
  if t == "Font" then return { family = tostring(v.Family), weight = tostring(v.Weight), style = tostring(v.Style), _t = t } end
  if t == "ColorSequence" or t == "NumberSequence" then
    local kp = {}
    for _, k in ipairs(v.Keypoints) do
      local okE, env = pcall(function() return k.Envelope end)
      table.insert(kp, { Time = k.Time, Value = conv(k.Value, depth + 1), Envelope = okE and env or nil })
    end
    return { kind = t, keypoints = kp, _t = t }
  end
  if type(v) == "number" or type(v) == "string" or type(v) == "boolean" then return v end
  if t == "Content" then
    -- The bridge's Content object carries the asset URI in .Uri; tostring() gives
    -- the debug form "Content(Uri=rbxassetid://123)". An empty Content has no URI,
    -- and must drop the property rather than render the string "Content(None)".
    local u = v.Uri
    if u == nil then return nil end
    local s = tostring(u)
    if s == "" then return nil end
    return s
  end
  -- Unknown datatype: hand back nil so the caller can name it. Returning
  -- tostring(t) here ("CFrame") would look like a value and hide the gap.
  return nil
end

-- Property reads are the emitter's cost. One read per name per instance, and every
-- name the class does not have raises an error whose stack traceback the bridge
-- formats before we throw it away. On AnimationEditorGUI (1479 instances, 137 names)
-- that is 202,623 reads: 1970-2091ms for the read pass plus 2108ms for the
-- `<name>Content` retry that followed every miss, out of a 5.6s emit. 78% of those reads
-- are for names the class cannot have at all (Frame has 23 of the 137 allowlisted names,
-- TextLabel 39, UICorner 6). Lune bundles rbx-dom's reflection database, so the real
-- property set of a class is available without guessing: read the ones that exist,
-- skip the rest. A name the class *does* have is never skipped: skipping it would
-- be a silent drop, which is the one thing this emitter exists to prevent, so the
-- first instance of every class is still read in full and the outcome compared
-- with the database (report_class_filter_mismatches below, printed every run).
local reflect = roblox.getReflectionDatabase()
local class_props = {}
-- Classes the database does not have. They are read in full, so nothing is filtered
-- away, but they cannot be compared against a property list the database does not
-- hold: that comparison would report every name the class lacks as a mismatch.
local unknown_classes = {}

local function class_property_set(className)
  local cached = class_props[className]
  if cached then return cached end
  local set, cur, reached_root = {}, reflect:GetClass(className), false
  local guard = 0
  while cur and guard < 16 do
    for name in pairs(cur.Properties) do set[name] = true end
    if cur.Name == "Instance" or cur.Name == "Object" then reached_root = true end
    local ok, next_class = pcall(function() return reflect:GetClass(cur.Superclass) end)
    if not ok then break end
    cur = next_class
    guard = guard + 1
  end
  -- A class whose chain does not reach the root is a class we do not understand.
  -- Read everything for it rather than a subset.
  if not reached_root then
    -- A copy, not PROPS_SET itself: this table is handed out as a per-class answer and
    -- cached, so an alias would let any caller that extends it change the allowlist for
    -- every class and every later run in the same process.
    local full = {}
    for name in pairs(PROPS_SET) do full[name] = true end
    set = full
    unknown_classes[className] = true
  end
  class_props[className] = set
  return set
end

-- A property the database does not list but the bridge hands over would be lost by
-- the filter above, so the first instance of each class is read in full anyway and
-- the two answers are compared. The counters print on every run.
--
-- What this check does NOT cover, because it is only as wide as the database it compares
-- against: instance-level divergence. Property existence is a class-level fact in rbx-dom
-- and reading every instance in full is the cost this change exists to remove, so a
-- property only some instances of a class answer is invisible here. A read that comes back
-- nil, or as an instance reference, is not counted either: nil is how the bridge answers
-- for a property that exists without a value.
local verified_classes = {}
local filter_mismatches = { narrow = 0, wide = 0, names = {} }

local function verify_class(inst, set)
  if verified_classes[inst.ClassName] then return end
  verified_classes[inst.ClassName] = true
  if unknown_classes[inst.ClassName] then return end
  for _, name in ipairs(PROPS) do
    local ok, value = pcall(function() return inst[name] end)
    if ok and value ~= nil and typeof(value) ~= "Instance" then
      if not set[name] then
        filter_mismatches.narrow = filter_mismatches.narrow + 1
        if #filter_mismatches.names < 8 then
          table.insert(filter_mismatches.names, inst.ClassName .. "." .. name)
        end
      end
    elseif not ok and set[name] then
      if string.find(tostring(value), "is not a valid member of", 1, true) then
        filter_mismatches.wide = filter_mismatches.wide + 1
        if #filter_mismatches.names < 8 then
          table.insert(filter_mismatches.names, "!" .. inst.ClassName .. "." .. name)
        end
      end
    end
  end
end

-- Some property types have no default value registered in the Lua bridge, so
-- reading them raises "Failed to get property 'Image' - missing default value"
-- (current rbx-dom Content/ContentId accessors). The old code pcall'd each read
-- and dropped failures, which silently deleted every asset id in the model and
-- produced an IR that rendered without images. Recover those names from the XML
-- view of the same instance: the value is plain text there.
-- rbx-dom escapes "&", "<" and ">" in property text, so a recovered value is the XML
-- spelling of the string until this runs: `cheap &amp; cheerful` reached the IR as itself.
local function unescape(text)
  if not string.find(text, "&", 1, true) then return text end
  text = string.gsub(text, "&lt;", "<")
  text = string.gsub(text, "&gt;", ">")
  text = string.gsub(text, "&quot;", '"')
  text = string.gsub(text, "&#(%d+);", function(code) return string.char(tonumber(code)) end)
  text = string.gsub(text, "&apos;", "'")
  -- last, so an escaped entity in the file stays escaped text rather than turning into
  -- the character it names
  return (string.gsub(text, "&amp;", "&"))
end

-- A recovered value has to keep the datatype its tag names, or it is not a value this
-- pass understands. The string "false" for `Visible` is truthy everywhere downstream
-- (flatten_node hides a node only on a real boolean false), so recovering `Visible` as
-- text turned a hidden object into a visible one, in silence. Scalars convert; anything
-- else (Ref, token, structs like UDim2/Color3) keeps the file's text as before, and a
-- struct the bridge cannot read is named in `unreadable` rather than guessed at.
local function from_xml(tag, text)
  if tag == "bool" then return text == "true" end
  if tag == "int" or tag == "int64" or tag == "float" or tag == "double" then
    return tonumber(text)
  end
  return unescape(text)
end

local function xml_props(inst, shallow)
  local target = inst
  local clone = nil
  if shallow then
    local okClone, cloned = pcall(function() return inst:Clone() end)
    if not okClone or cloned == nil then return {}, {} end
    clone = cloned
    target = clone
    for _, child in ipairs(clone:GetChildren()) do child:Destroy() end
  end
  local ok, xml = pcall(function() return roblox.serializeModel({ target }, { xml = true }) end)
  if clone ~= nil then clone:Destroy() end
  if not ok then return {}, {} end
  -- first <Properties> block belongs to this instance, children come after it
  local block = string.match(xml, "<Properties>(.-)</Properties>")
  local found, present = {}, {}
  if block then
    for tag, name, value in string.gmatch(block, "<([%w]+) name=\"([%w_]+)\">([^<]*)</") do
      present[name] = true
      if value ~= "" and found[name] == nil then found[name] = from_xml(tag, value) end
    end
    -- Content values nest the URI: <Content name="Image"><uri>rbxassetid://123</uri>
    for name, value in string.gmatch(block, "name=\"([%w_]+)\"><[uU][rR][lL]>(.-)</[uU][rR][lL]>") do
      present[name] = true
      if value ~= "" and found[name] == nil then found[name] = unescape(value) end
    end
    for name in string.gmatch(block, "<[%w]+ name=\"([%w_]+)\"") do
      present[name] = true
    end
  end
  return found, present
end

local function parse_property_block(block)
  local found, present = {}, {}
  for tag, name, value in string.gmatch(block, "<([%w]+) name=\"([%w_]+)\">([^<]*)</") do
    present[name] = true
    if value ~= "" and found[name] == nil then found[name] = from_xml(tag, value) end
  end
  for name, value in string.gmatch(block, "name=\"([%w_]+)\"><[uU][rR][lL]>(.-)</[uU][rR][lL]>") do
    present[name] = true
    if value ~= "" and found[name] == nil then found[name] = unescape(value) end
  end
  for name in string.gmatch(block, "<[%w]+ name=\"([%w_]+)\"") do
    present[name] = true
  end
  return found, present
end

-- `xml_props` below serializes one instance *and its whole subtree* per call, and it
-- is called once per instance: that is O(nodes x subtree) native work, and stubbing
-- it out took AnimationEditorGUI's emit from 6217ms to 5018ms. The file's text is in
-- memory, rbx-dom writes items in tree order, so one serialization of the whole
-- model answers every instance. Item N is instance N only if rbx-dom keeps that
-- order, so the class attribute of every item is checked against the tree before
-- the index is used; any doubt and the per-instance call stays in charge.
local function xml_visual_index(roots, classes, keep_map)
  -- Fast profiles only need XML fallback values for retained visual nodes. Clone the
  -- retained roots once, prune runtime-only subtrees from the clones, and serialize
  -- that reduced tree. Originals are never mutated.
  local clones = {}
  local prune_ok = true
  local function prune(original, clone)
    local original_children = original:GetChildren()
    local clone_children = clone:GetChildren()
    if #original_children ~= #clone_children then
      prune_ok = false
      return
    end
    for idx = 1, #original_children do
      local original_child = original_children[idx]
      local clone_child = clone_children[idx]
      if keep_map[original_child] then
        prune(original_child, clone_child)
      else
        clone_child:Destroy()
      end
    end
  end
  for _, root in ipairs(roots) do
    if keep_map[root] then
      local ok_clone, clone = pcall(function() return root:Clone() end)
      if not ok_clone or clone == nil then
        prune_ok = false
        break
      end
      prune(root, clone)
      table.insert(clones, clone)
    end
  end
  if not prune_ok then
    for _, clone in ipairs(clones) do clone:Destroy() end
    return nil
  end
  local ok, xml = pcall(function() return roblox.serializeModel(clones, { xml = true }) end)
  for _, clone in ipairs(clones) do clone:Destroy() end
  if not ok then return nil end
  local items, count, pos = {}, 0, 1
  while true do
    local s, e, close, tag = string.find(xml, "<(/?)([A-Za-z]+)", pos)
    if not s then break end
    if tag == "Item" and close == "" then
      count = count + 1
      local cls = string.match(string.sub(xml, e + 1, e + 64), "class=\"([%w_]+)\"")
      items[count] = { class = cls, found = {}, present = {} }
      pos = e + 1
    elseif tag == "Properties" and close == "" then
      local stop = string.find(xml, "</Properties>", e + 1, true)
      local cur = items[count]
      if cur then
        local block = string.sub(xml, e + 1, (stop or #xml + 1) - 1)
        for name in pairs(VISUAL_XML_RECOVERY) do
          if string.find(block, 'name="' .. name .. '"', 1, true) then
            cur.present[name] = true
            local tagName, value =
              string.match(block, '<([%w]+) name="' .. name .. '">([^<]*)</')
            if tagName ~= nil and value ~= nil and value ~= "" then
              cur.found[name] = from_xml(tagName, value)
            end
          end
        end
      end
      pos = stop and stop + 13 or (e + 1)
    else
      pos = e + 1
    end
  end
  if count ~= #classes then
    print("visual xml index: rejected, " .. tostring(count) .. " items for "
      .. tostring(#classes) .. " instances; using shallow fallback")
    return nil
  end
  for idx = 1, count do
    if items[idx].class ~= classes[idx] then
      print("visual xml index: rejected at item " .. tostring(idx) .. "; using shallow fallback")
      return nil
    end
  end
  return items
end

local function xml_index(roots, classes)
  local ok, xml = pcall(function() return roblox.serializeModel(roots, { xml = true }) end)
  if not ok then return nil end
  local items, count, pos = {}, 0, 1
  while true do
    local s, e, close, tag = string.find(xml, "<(/?)([A-Za-z]+)", pos)
    if not s then break end
    if tag == "Item" and close == "" then
      count = count + 1
      local cls = string.match(string.sub(xml, e + 1, e + 64), "class=\"([%w_]+)\"")
      items[count] = { class = cls, found = {}, present = {} }
      pos = e + 1
    elseif tag == "Properties" and close == "" then
      local stop = string.find(xml, "</Properties>", e + 1, true)
      local cur = items[count]
      if cur then
        cur.found, cur.present =
          parse_property_block(string.sub(xml, e + 1, (stop or #xml + 1) - 1))
      end
      pos = stop and stop + 13 or (e + 1)
    else
      pos = e + 1
    end
  end
  if count ~= #classes then
    print("xml index: rejected, " .. tostring(count) .. " items for " .. tostring(#classes)
      .. " instances; falling back to one serialization per instance")
    return nil
  end
  for idx = 1, count do
    if items[idx].class ~= classes[idx] then
      print("xml index: rejected, item " .. tostring(idx) .. " is a " .. tostring(items[idx].class)
        .. " where the tree has a " .. tostring(classes[idx]) .. "; falling back")
      return nil
    end
  end
  return items
end

local function preorder_classes(roots, keep_map)
  local out = {}
  local function rec(inst)
    if keep_map ~= nil and not keep_map[inst] then return end
    table.insert(out, inst.ClassName)
    for _, child in ipairs(inst:GetChildren()) do rec(child) end
  end
  for _, r in ipairs(roots) do rec(r) end
  return out
end

local emission_profile = process.args[3] or "full"
local node_index = 0
local xml_items = nil
local visual_keep = {}

local function walk(inst)
  if emission_profile ~= "full" and not visual_keep[inst] then return nil end
  node_index = node_index + 1
  local xml = xml_items and xml_items[node_index]
  if xml_items and (xml == nil or xml.class ~= inst.ClassName) then
    error("emitter: the XML index does not line up at instance " .. tostring(node_index))
  end
  local children = inst:GetChildren()

  -- A non-visual ancestor is retained only to preserve hierarchy/full-name paths.
  -- Keep the model pivot inputs here too: scene/preview uses the static profile,
  -- and dropping them would silently revert Scale to the default fallback.
  if emission_profile ~= "full" and not profile_keeps_class(emission_profile, inst.ClassName) then
    local props = {}
    if inst.ClassName == "Model" then
      for _, name in ipairs({ "Scale", "WorldPivot" }) do
        local okValue, value = pcall(function() return inst[name] end)
        if okValue and value ~= nil then
          local converted = conv(value)
          if converted ~= nil then props[name] = converted end
        end
      end
      local okPrimary, primary = pcall(function() return inst.PrimaryPart end)
      if okPrimary and primary ~= nil and typeof(primary) == "Instance" then
        local okName, fullName = pcall(function() return primary:GetFullName() end)
        if okName and fullName ~= nil then props.PrimaryPart = fullName end
      end
    end
    local node = { className = inst.ClassName, name = inst.Name, props = props, children = {} }
    for _, child in ipairs(children) do
      local child_node = walk(child)
      if child_node ~= nil then table.insert(node.children, child_node) end
    end
    return node
  end

  local valid = class_property_set(inst.ClassName)
  verify_class(inst, valid)
  -- Allowlisted names that this class has no property for but a child is called:
  -- the bridge answers `frame.Padding` with the *child* of that name, and feeding
  -- that on is worse than dropping it (flatten_node is name-driven, so a Frame with
  -- a child named "Text" would render the word "Instance"). Named, not read.
  local child_named = {}
  for _, child in ipairs(children) do
    if PROPS_SET[child.Name] and not valid[child.Name] then
      child_named[child.Name] = child.ClassName
    end
  end
  local props = {}
  local found, present = xml and xml.found, xml and xml.present
  local unreadable = {}
  local unmapped = {}
  local not_a_property = {}
  for _, name in ipairs(PROPS) do
    local ok, value, child_fallback
    if valid[name] then
      ok, value = pcall(function() return inst[name] end)
    else
      -- Not a property of this class: no read, no error, no stack traceback. It
      -- can still be a child's name, which the map above already knows about.
      child_fallback = child_named[name]
    end
    if value ~= nil and typeof(value) == "Instance" then
      if name == "Adornee" or name == "Attachment0" or name == "Attachment1" or name == "PrimaryPart" then
        -- Preserve references as stable names; the browser resolves them in-tree.
        local okName, fullName = pcall(function() return value:GetFullName() end)
        if okName and fullName ~= nil then value = fullName else value = nil end
      else
        -- An instance here is usually a child whose name collided with a
        -- reflected property. Do not feed it to the flatten schema.
        child_fallback = value.ClassName
        value = nil
      end
    end
    if valid[name] and (not ok or value == nil) then
      -- Roblox renamed the ContentId properties (`Image` -> `ImageContent`). In
      -- current rbx-dom builds the legacy name has no default value and cannot be
      -- read at all, while the renamed one reads fine. Report it under the legacy
      -- name so the flatten schema, which keys off `Image`, still applies.
      local content_name = CONTENT_PROPERTY_ALIASES[name] or (name .. "Content")
      local ok2, value2 = pcall(function() return inst[content_name] end)
      if ok2 and value2 ~= nil and typeof(value2) ~= "Instance" then
        ok, value, child_fallback = true, value2, nil
      end
    end
    if ok and value ~= nil then
      local c = conv(value)
      if c ~= nil then
        props[name] = c
      elseif typeof(value) ~= "Content" then
        -- Unmappable datatype. Name it on the node instead of dropping it: an
        -- empty Content is the one value that legitimately disappears.
        table.insert(unmapped, name .. " (" .. typeof(value) .. ")")
      end
    elseif child_fallback then
      -- Not a property of this class at all: the name belongs to a child. Nothing
      -- was lost, so this is informational, not a drop.
      table.insert(not_a_property, name .. " (child " .. child_fallback .. ")")
    else
      if emission_profile ~= "full" then
        if VISUAL_XML_RECOVERY[name] then
          if present == nil then found, present = xml_props(inst, true) end
          local raw = found[name]
          if raw ~= nil then props[name] = raw end
        end
      else
        if present == nil then found, present = xml_props(inst) end
        local raw = found[name]
        if raw ~= nil then
          props[name] = raw
        elseif present[name] then
          -- the file carries it, the bridge will not hand it over, nothing to
          -- recover it from: name it rather than dropping it in silence
          table.insert(unreadable, name)
        end
      end
    end
  end
  local node = { className = inst.ClassName, name = inst.Name, props = props, children = {} }
  if #unreadable > 0 then node.unreadable = unreadable end
  if #unmapped > 0 then node.unmapped = unmapped end
  if #not_a_property > 0 then node.not_a_property = not_a_property end
  for _, child in ipairs(children) do
    local child_node = walk(child)
    if child_node ~= nil then table.insert(node.children, child_node) end
  end
  return node
end

local path, out = process.args[1], process.args[2]
if not path or not out or (emission_profile ~= "full" and emission_profile ~= "visual" and emission_profile ~= "static") then
  print("usage: lune run scripts/rhr-ir.luau <source.rbxm|.rbxmx|.rbxl> <out.json> [full|visual|static]")
  process.exit(1)
end
local data = fs.readFile(path)
local roots
local ok = pcall(function() roots = roblox.deserializeModel(data) end)
if not ok then roots = roblox.deserializePlace(data) end
local node_classes = preorder_classes(roots)
if emission_profile ~= "full" then
  local function mark(inst)
    local keep = profile_keeps_class(emission_profile, inst.ClassName)
    for _, child in ipairs(inst:GetChildren()) do
      keep = mark(child) or keep
    end
    visual_keep[inst] = keep
    return keep
  end
  for _, root in ipairs(roots) do mark(root) end
end
if emission_profile == "full" then
  xml_items = xml_index(roots, node_classes)
else
  local retained_classes = preorder_classes(roots, visual_keep)
  xml_items = xml_visual_index(roots, retained_classes, visual_keep)
end
local nodes = {}
for _, r in ipairs(roots) do
  local node = walk(r)
  if node ~= nil then table.insert(nodes, node) end
end
fs.writeFile(out, serde.encode("json", { sourcePath = path, roots = nodes }))

-- Never silent: report properties the file carries that we could not read, and
-- properties whose datatype we could not map. Either one is a rendering bug
-- waiting to happen, so the counts print on every run.
local names, unmapped_names = {}, {}
local nodes_affected, unmapped_nodes, collision_nodes = 0, 0, 0
local function count(node)
  if node.unreadable then
    nodes_affected = nodes_affected + 1
    for _, name in ipairs(node.unreadable) do names[name] = (names[name] or 0) + 1 end
  end
  if node.unmapped then
    unmapped_nodes = unmapped_nodes + 1
    for _, name in ipairs(node.unmapped) do unmapped_names[name] = (unmapped_names[name] or 0) + 1 end
  end
  if node.not_a_property then
    collision_nodes = collision_nodes + 1
  end
  for _, child in ipairs(node.children) do count(child) end
end
for _, r in ipairs(nodes) do count(r) end
local function tally(counts)
  local out = {}
  for name, n in pairs(counts) do table.insert(out, name .. "x" .. tostring(n)) end
  table.sort(out)
  return table.concat(out, ", ")
end
print("wrote " .. out .. " roots=" .. #nodes)
print("unreadable: " .. tostring(nodes_affected) .. " nodes"
  .. (next(names) and (", " .. tally(names)) or ""))
print("unmapped: " .. tostring(unmapped_nodes) .. " nodes"
  .. (next(unmapped_names) and (", " .. tally(unmapped_names)) or ""))
-- Property names that are really child names (a Frame with a child called
-- "Padding" answers frame.Padding with the child). Nothing was dropped; the count
-- is here so a sudden jump is visible.
print("name collisions: " .. tostring(collision_nodes) .. " nodes")
-- The class filter is one table lookup away from losing a property, so its answer is
-- checked against a full read of the first instance of every class (see verify_class).
local unknown_count = 0
for _ in pairs(unknown_classes) do unknown_count = unknown_count + 1 end
print("class filter: " .. tostring(#node_classes) .. " instances over "
  .. tostring(filter_mismatches.narrow + filter_mismatches.wide) .. " database mismatches"
  .. (#filter_mismatches.names > 0 and (", e.g. " .. table.concat(filter_mismatches.names, ", ")) or "")
  .. (unknown_count > 0 and (", " .. tostring(unknown_count) .. " class(es) not in the database read in full") or ""))
-- A "narrow" mismatch is a value the bridge hands over for a name the database does
-- not list for that class: the filter would skip it on every other instance, so the
-- IR above is missing properties. Refuse it rather than ship it.
if filter_mismatches.narrow > 0 then
  print("emitter: the reflection database is narrower than the bridge on "
    .. tostring(filter_mismatches.narrow) .. " names; the IR written to " .. out
    .. " may be missing them")
  process.exit(1)
end