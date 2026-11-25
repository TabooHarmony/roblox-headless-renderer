-- What UI Labs' Environment module does with getfenv(): read a key from the caller's
-- environment and treat nil as "not run by the UI Labs plugin".
local EnvProbe = {}

function EnvProbe.injection(): any
	local env = getfenv()
	return env["__hotreload_env_global_injection__"]
end

function EnvProbe.reachesLune(): boolean
	local env = getfenv()
	return env.process ~= nil or env.fs ~= nil or env.net ~= nil
end

return EnvProbe
