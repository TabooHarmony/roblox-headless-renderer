-- rhr-ir.luau for many files in one Lune process (rhr.lune_worker).
--
-- Starting Lune and the script costs about half a second, most of what converting a
-- small XML model takes. The resident server keeps this loop running instead: it
-- compiles rhr-ir.luau once and runs it as a fresh chunk for every request, so no
-- state is shared between files.
--
-- Usage: lune run rhr-ir-serve.luau <path to rhr-ir.luau>
-- Each request is one line on stdin: source TAB out TAB profile. The reply on stdout is
-- what the script printed, one line each, then a line of ASCII 30 followed by "ok" or
-- "error <message>". An empty line or the end of stdin ends the loop.

local fs = require("@lune/fs")
local luau = require("@lune/luau")
local process = require("@lune/process")
local stdio = require("@lune/stdio")

local bytecode = luau.compile(fs.readFile(process.args[1]))

while true do
  local line = stdio.readLine()
  if line == nil then break end
  line = string.gsub(line, "[\r\n]+$", "")
  if line == "" then break end
  local fields = string.split(line, "\t")
  local printed = {}
  local chunk = luau.load(bytecode, {
    debugName = "rhr-ir",
    environment = {
      print = function(...)
        local parts = table.pack(...)
        for index = 1, parts.n do parts[index] = tostring(parts[index]) end
        table.insert(printed, table.concat(parts, "\t", 1, parts.n))
      end,
    },
  })
  local ok, err = pcall(chunk, fields[1], fields[2], fields[3])
  local status = ok and "ok" or ("error " .. string.gsub(tostring(err), "[\r\n]+", " "))
  local body = table.concat(printed, "\n")
  stdio.write((#printed > 0 and (body .. "\n") or "") .. "\30" .. status .. "\n")
end
