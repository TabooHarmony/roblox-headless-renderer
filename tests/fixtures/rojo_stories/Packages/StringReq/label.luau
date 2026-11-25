local up = require("../Mini")
local deeper = require("./inner/leaf")
return { text = if up ~= nil and deeper.ok then "strings" else "wrong" }
