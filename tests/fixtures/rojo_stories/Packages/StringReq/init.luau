-- An init module: "@self/x" is its child, "./x" a sibling of its folder.
local label = require("@self/label")
local sibling = require("./Mini")
return { text = label.text, sibling = sibling ~= nil }
