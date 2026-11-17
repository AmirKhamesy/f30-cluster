local mem = ac.writeMemoryMappedFile('F30Cluster', [[
  uint8_t left, right, hazard, phase, headlights;
]])

local function b(v) return v and 1 or 0 end

function script.update()
  local car = ac.getCar(0)
  if not car then return end
  mem.left = b(car.turningLeftLights)
  mem.right = b(car.turningRightLights)
  mem.hazard = b(car.hazardLights)
  mem.phase = b(car.turningLightsActivePhase)
  mem.headlights = b(car.headlightsActive)
end

function windowMain()
  ui.text(string.format('left %d  right %d  hazard %d  lights %d', mem.left, mem.right, mem.hazard, mem.headlights))
end
