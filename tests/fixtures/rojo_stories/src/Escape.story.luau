-- Reaching Lune's own require through the environment (see story-runtime.luau).
return function(target)
	local process = getfenv(0).require("@lune/process")
	process.exit(0)
end
