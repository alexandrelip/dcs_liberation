-- the state.json file will be updated according to this schedule, and also on each destruction or capture event
local WRITESTATE_SCHEDULE_IN_SECONDS = 60

logger = mist.Logger:new("DCSLiberation", "info")
logger:info("Check that json.lua is loaded : json = "..tostring(json))

last_write_simulation_time_seconds = 0
simulation_time_seconds = 0
crash_events = {} -- killed aircraft will be added via S_EVENT_CRASH event
dead_events = {} -- killed units will be added via S_EVENT_DEAD event
unit_lost_events = {} -- killed units will be added via S_EVENT_UNIT_LOST
kill_events = {} -- killed units will be added via S_EVENT_KILL 
base_capture_events = {}
destroyed_objects_positions = {} -- will be added via S_EVENT_DEAD event
killed_ground_units = {} -- keep track of static ground object deaths
unit_hit_point_updates = {} -- stores updates to unit hit points, triggered by S_EVENT_HIT
mission_ended = false

local AI_COHORT_WINDOW_SECONDS = 1
local AI_GROUP_REFRESH_SECONDS = 5
local ai_managed_groups = {}
local ai_enabled_groups = {}
local ai_group_cursor = 1
local ai_last_refresh_time = -math.huge
local deferred_ground_group_names = {}
local activation_anchor_group_names = {}
local activated_force_counts = {
    blue = {
        samSites = 0,
        samSiteNames = {},
        ships = 0,
        groundVehicles = 0,
        infantry = 0
    },
    red = {
        samSites = 0,
        samSiteNames = {},
        ships = 0,
        groundVehicles = 0,
        infantry = 0
    }
}

if dcsLiberation and dcsLiberation.DeferredGroundGroups then
    for _, data in pairs(dcsLiberation.DeferredGroundGroups) do
        deferred_ground_group_names[data.dcsGroupName] = true
    end
end
if dcsLiberation and dcsLiberation.ActivationAnchorGroups then
    for _, group_name in pairs(dcsLiberation.ActivationAnchorGroups) do
        activation_anchor_group_names[group_name] = true
    end
end

local function configured_ground_ai_percent()
    if dcsLiberation and dcsLiberation.Performance then
        local configured = tonumber(dcsLiberation.Performance.groundAiActivePercent)
        if configured then
            return math.max(5, math.min(100, configured))
        end
    end
    return 15
end

local function carrier_group_names()
    local names = {}
    if dcsLiberation and dcsLiberation.Carriers then
        for _, carrier in pairs(dcsLiberation.Carriers) do
            names[carrier.dcsGroupName] = true
        end
    end
    return names
end

local function unit_is_active(unit)
    if not unit:isExist() then
        return false
    end
    local success, active = pcall(function()
        return unit:isActive()
    end)
    return success and active
end

local function group_is_active(group)
    if not group or not group:isExist() then
        return false
    end
    for _, unit in ipairs(group:getUnits()) do
        if unit_is_active(unit) then
            return true
        end
    end
    return false
end

local function group_has_player(group)
    for _, unit in ipairs(group:getUnits()) do
        if unit_is_active(unit) and unit:getPlayerName() then
            return true
        end
    end
    return false
end

local function set_group_ai(group, enabled)
    if not group_is_active(group) then
        return false
    end
    local success, error_message = pcall(function()
        local controller = group:getController()
        if controller then
            controller:setOnOff(enabled)
        end
    end)
    if not success then
        logger:warn(
            "Unable to set AI state for "..group:getName()..": "..tostring(error_message)
        )
    end
    return success
end

local function refresh_managed_ai_groups()
    local previous_groups = ai_managed_groups
    local carriers = carrier_group_names()
    local groups_by_name = {}
    local sides = {coalition.side.BLUE, coalition.side.RED}
    local categories = {Group.Category.GROUND, Group.Category.SHIP}

    for _, side in ipairs(sides) do
        for _, category in ipairs(categories) do
            local groups = coalition.getGroups(side, category)
            if groups then
                for _, group in ipairs(groups) do
                    if (
                        group_is_active(group)
                        and group:getSize() > 0
                        and not carriers[group:getName()]
                        and not group_has_player(group)
                    ) then
                        groups_by_name[group:getName()] = group
                    end
                end
            end
        end
    end

    ai_managed_groups = {}
    for _, group in pairs(groups_by_name) do
        ai_managed_groups[#ai_managed_groups + 1] = group
    end
    table.sort(ai_managed_groups, function(left, right)
        return left:getName() < right:getName()
    end)

    for _, group in ipairs(previous_groups) do
        if not groups_by_name[group:getName()] then
            set_group_ai(group, true)
        end
    end
    for _, group in ipairs(ai_managed_groups) do
        set_group_ai(group, false)
    end

    ai_enabled_groups = {}
    if ai_group_cursor > #ai_managed_groups then
        ai_group_cursor = 1
    end
end

local function disable_ai_cohort()
    for _, group in ipairs(ai_enabled_groups) do
        set_group_ai(group, false)
    end
    ai_enabled_groups = {}
end

local function update_ai_cohort(_, schedule_time)
    if mission_ended then
        for _, group in ipairs(ai_managed_groups) do
            set_group_ai(group, true)
        end
        return nil
    end

    if schedule_time - ai_last_refresh_time >= AI_GROUP_REFRESH_SECONDS then
        refresh_managed_ai_groups()
        ai_last_refresh_time = schedule_time
    end

    disable_ai_cohort()

    local group_count = #ai_managed_groups
    if group_count == 0 then
        return schedule_time + AI_COHORT_WINDOW_SECONDS
    end

    local active_percent = configured_ground_ai_percent()
    local exact_active_count = group_count * active_percent / 100
    local active_count = math.floor(exact_active_count)
    local active_duration = AI_COHORT_WINDOW_SECONDS
    if active_count == 0 then
        active_count = 1
        active_duration = exact_active_count * AI_COHORT_WINDOW_SECONDS
    end
    for offset = 0, active_count - 1 do
        local index = ((ai_group_cursor + offset - 1) % group_count) + 1
        local group = ai_managed_groups[index]
        if set_group_ai(group, true) then
            ai_enabled_groups[#ai_enabled_groups + 1] = group
        end
    end
    ai_group_cursor = ((ai_group_cursor + active_count - 1) % group_count) + 1

    if active_duration < AI_COHORT_WINDOW_SECONDS then
        timer.scheduleFunction(
            disable_ai_cohort,
            nil,
            schedule_time + active_duration
        )
    end
    return schedule_time + AI_COHORT_WINDOW_SECONDS
end

timer.scheduleFunction(update_ai_cohort, nil, timer.getTime() + 1)

local function active_unit_positions()
    local positions = {}
    if dcsLiberation and dcsLiberation.ActivationAnchorPoints then
        for _, position in pairs(dcsLiberation.ActivationAnchorPoints) do
            positions[#positions + 1] = {
                x = tonumber(position.positionX),
                y = 0,
                z = tonumber(position.positionY)
            }
        end
    end
    local sides = {coalition.side.BLUE, coalition.side.RED}
    local categories = {
        Group.Category.AIRPLANE,
        Group.Category.HELICOPTER,
        Group.Category.GROUND,
        Group.Category.SHIP
    }
    for _, side in ipairs(sides) do
        for _, category in ipairs(categories) do
            local groups = coalition.getGroups(side, category)
            if groups then
                for _, group in ipairs(groups) do
                    if (
                        group_is_active(group)
                        and not deferred_ground_group_names[group:getName()]
                        and (
                            activation_anchor_group_names[group:getName()]
                            or group_has_player(group)
                        )
                    ) then
                        for _, unit in ipairs(group:getUnits()) do
                            if unit_is_active(unit) then
                                positions[#positions + 1] = unit:getPoint()
                            end
                        end
                    end
                end
            end
        end
    end
    return positions
end

local function force_limit(coalition_name, name, default)
    if dcsLiberation and dcsLiberation.ForceLimits then
        local coalition_limits = dcsLiberation.ForceLimits[coalition_name]
        if coalition_limits then
            return tonumber(coalition_limits[name]) or default
        end
    end
    return default
end

local function deferred_group_has_capacity(data)
    local counts = activated_force_counts[data.coalition]
    if not counts then
        return false
    end
    if data.kind == "sam" then
        if counts.samSiteNames[data.siteName] then
            return true
        end
        return counts.samSites < force_limit(data.coalition, "samSites", 3)
    end
    if data.kind == "ship" then
        return (
            counts.ships + tonumber(data.unitCount)
            <= force_limit(data.coalition, "ships", 6)
        )
    end
    if data.kind == "ground" then
        return (
            counts.groundVehicles + tonumber(data.unitCount)
            <= force_limit(data.coalition, "groundVehicles", 15)
        )
    end
    if data.kind == "infantry" then
        return (
            counts.infantry + tonumber(data.unitCount)
            <= force_limit(data.coalition, "infantry", 5)
        )
    end
    return false
end

local function record_deferred_group_activation(data)
    local counts = activated_force_counts[data.coalition]
    if data.kind == "sam" then
        if not counts.samSiteNames[data.siteName] then
            counts.samSiteNames[data.siteName] = true
            counts.samSites = counts.samSites + 1
        end
    elseif data.kind == "ship" then
        counts.ships = counts.ships + tonumber(data.unitCount)
    elseif data.kind == "ground" then
        counts.groundVehicles = counts.groundVehicles + tonumber(data.unitCount)
    elseif data.kind == "infantry" then
        counts.infantry = counts.infantry + tonumber(data.unitCount)
    end
end

local function update_deferred_ground_groups(_, schedule_time)
    if not dcsLiberation or not dcsLiberation.DeferredGroundGroups then
        return nil
    end

    local positions = active_unit_positions()
    local pending = {}
    for _, data in pairs(dcsLiberation.DeferredGroundGroups) do
        local position_x = tonumber(data.positionX)
        local position_y = tonumber(data.positionY)
        local activation_distance = tonumber(data.activationDistance)
        local activation_distance_squared = activation_distance * activation_distance
        local should_activate = false
        for _, position in ipairs(positions) do
            local offset_x = position.x - position_x
            local offset_y = position.z - position_y
            if offset_x * offset_x + offset_y * offset_y <= activation_distance_squared then
                should_activate = true
                break
            end
        end

        if should_activate and deferred_group_has_capacity(data) then
            local group = Group.getByName(data.dcsGroupName)
            if group then
                trigger.action.activateGroup(group)
                record_deferred_group_activation(data)
                set_group_ai(group, false)
                ai_last_refresh_time = -math.huge
                logger:info("Activated deferred ground group "..data.dcsGroupName)
            end
        elseif deferred_group_has_capacity(data) then
            pending[#pending + 1] = data
        end
    end

    dcsLiberation.DeferredGroundGroups = pending
    if #pending > 0 then
        return schedule_time + 10
    end
    return nil
end

timer.scheduleFunction(update_deferred_ground_groups, nil, timer.getTime() + 1)

local mig29_retreating_groups = {}
local mig29_types = {
    ["MiG-29A"] = true,
    ["MiG-29G"] = true,
    ["MiG-29S"] = true
}

local function active_aircraft_near(side, center, radius_squared)
    local count = 0
    local groups = coalition.getGroups(side, Group.Category.AIRPLANE)
    if not groups then
        return count
    end
    for _, group in ipairs(groups) do
        if group_is_active(group) then
            for _, unit in ipairs(group:getUnits()) do
                if unit_is_active(unit) and unit:inAir() then
                    local point = unit:getPoint()
                    local offset_x = point.x - center.x
                    local offset_y = point.z - center.z
                    if (
                        offset_x * offset_x + offset_y * offset_y
                        <= radius_squared
                    ) then
                        count = count + 1
                    end
                end
            end
        end
    end
    return count
end

local function nearest_active_red_sam(point)
    local best = nil
    local best_distance = math.huge
    if not dcsLiberation or not dcsLiberation.DefensiveSamPoints then
        return nil
    end
    for _, data in pairs(dcsLiberation.DefensiveSamPoints) do
        local group = Group.getByName(data.dcsGroupName)
        if group_is_active(group) then
            local offset_x = tonumber(data.positionX) - point.x
            local offset_y = tonumber(data.positionY) - point.z
            local distance = offset_x * offset_x + offset_y * offset_y
            if distance < best_distance then
                best_distance = distance
                best = data
            end
        end
    end
    return best
end

local function retreat_mig29_to_sam(group, current, sam)
    local altitude = math.max(current.y, 3500)
    local speed = 250
    local sam_point = {
        x = tonumber(sam.positionX),
        y = tonumber(sam.positionY)
    }
    local route = {
        mist.fixedWing.buildWP(current, "turningpoint", speed, altitude, "baro"),
        mist.fixedWing.buildWP(
            sam_point,
            "turningpoint",
            speed,
            altitude,
            "baro"
        )
    }
    route[2].task = {
        id = "ComboTask",
        params = {
            tasks = {
                {
                    enabled = true,
                    auto = false,
                    id = "Orbit",
                    number = 1,
                    params = {
                        pattern = "Circle",
                        point = sam_point,
                        speed = speed,
                        altitude = altitude
                    }
                }
            }
        }
    }
    if mist.goRoute(group, route) then
        mig29_retreating_groups[group:getName()] = true
        logger:info(
            "MiG-29 group "..group:getName()..
            " retreating to SAM cover "..sam.dcsGroupName
        )
    end
end

local function update_mig29_retreats(_, schedule_time)
    if (
        not dcsLiberation
        or not dcsLiberation.Performance
        or dcsLiberation.Performance.mig29RetreatToSam ~= "true"
    ) then
        return nil
    end

    local radius = tonumber(
        dcsLiberation.Performance.mig29OutnumberedRadius
    ) or 120000
    local radius_squared = radius * radius
    local groups = coalition.getGroups(
        coalition.side.RED,
        Group.Category.AIRPLANE
    )
    if groups then
        for _, group in ipairs(groups) do
            if (
                group_is_active(group)
                and not mig29_retreating_groups[group:getName()]
            ) then
                local units = group:getUnits()
                local lead = units and units[1]
                if (
                    lead
                    and unit_is_active(lead)
                    and lead:inAir()
                    and mig29_types[lead:getTypeName()]
                ) then
                    local point = lead:getPoint()
                    local friendly = active_aircraft_near(
                        coalition.side.RED,
                        point,
                        radius_squared
                    )
                    local hostile = active_aircraft_near(
                        coalition.side.BLUE,
                        point,
                        radius_squared
                    )
                    if hostile > friendly then
                        local sam = nearest_active_red_sam(point)
                        if sam then
                            retreat_mig29_to_sam(group, point, sam)
                        end
                    end
                end
            end
        end
    end
    return schedule_time + 10
end

timer.scheduleFunction(update_mig29_retreats, nil, timer.getTime() + 10)

local function collect_aircraft_states()
    local aircraft_states = {}
    local sides = {coalition.side.BLUE, coalition.side.RED}
    local categories = {Group.Category.AIRPLANE, Group.Category.HELICOPTER}
    for _, side in ipairs(sides) do
        for _, category in ipairs(categories) do
            local groups = coalition.getGroups(side, category)
            if groups then
                for _, group in ipairs(groups) do
                    local units = group:getUnits()
                    for _, unit in ipairs(units) do
                        if unit_is_active(unit) then
                            local success, state = pcall(function()
                                local point = unit:getPoint()
                                local ammo_remaining = 0
                                local ammo = unit:getAmmo()
                                if ammo then
                                    for _, store in ipairs(ammo) do
                                        ammo_remaining = ammo_remaining + (store.count or 0)
                                    end
                                end
                                return {
                                    ["name"] = unit:getName(),
                                    ["x"] = point.x,
                                    ["y"] = point.z,
                                    ["altitude"] = point.y,
                                    ["fuel_fraction"] = unit:getFuel(),
                                    ["life"] = unit:getLife(),
                                    ["life_initial"] = unit:getLife0(),
                                    ["in_air"] = unit:inAir(),
                                    ["ammo_remaining"] = ammo_remaining
                                }
                            end)
                            if success then
                                aircraft_states[#aircraft_states + 1] = state
                            end
                        end
                    end
                end
            end
        end
    end
    return aircraft_states
end

local function ends_with(str, ending)
   return ending == "" or str:sub(-#ending) == ending
end

local function messageAll(message)
    local msg = {}
    msg.text = message
    msg.displayTime = 25
    msg.msgFor = {coa = {'all'}}
    mist.message.add(msg)
end

function write_state()
    simulation_time_seconds = timer.getTime()
    if not mission_ended and simulation_time_seconds - last_write_simulation_time_seconds < WRITESTATE_SCHEDULE_IN_SECONDS then
        return nil
    end

    local _debriefing_file_location = debriefing_file_location
    if not debriefing_file_location then 
        _debriefing_file_location = "[nil]"
    end

    local fp = io.open(_debriefing_file_location, 'w')
    local game_state = {
        ["crash_events"] = crash_events,
        ["dead_events"] = dead_events,
        ["base_capture_events"] = base_capture_events,
		["unit_lost_events"] = unit_lost_events,
		["kill_events"] = kill_events,
        ["mission_ended"] = mission_ended,
        ["destroyed_objects_positions"] = destroyed_objects_positions,
		["killed_ground_units"] = killed_ground_units,
		["unit_hit_point_updates"] = unit_hit_point_updates,
		["aircraft_states"] = collect_aircraft_states(),
		["simulation_time_seconds"] = simulation_time_seconds
    }
    if not json then
        local message = string.format("Unable to save DCS Liberation state to %s, JSON library is not loaded !", _debriefing_file_location)
        logger:error(message)
        messageAll(message)
    end
    fp:write(json:encode(game_state))
    fp:close()
    last_write_simulation_time_seconds = simulation_time_seconds
end

local function canWrite(name)
    local f = io.open(name, "w")
    if f then
        f:close()
        return true
    end
    return false
end

local function testDebriefingFilePath(folderPath, folderName, useCurrentStamping)
    if folderPath then
        local filePath = nil
        if not ends_with(folderPath, "\\") then
            folderPath = folderPath .. "\\"
        end
        if useCurrentStamping then
            filePath = string.format("%sstate-%s.json",folderPath, tostring(os.time()))
        else 
            filePath = string.format("%sstate.json",folderPath)
        end
        local isOk = canWrite(filePath)
        if isOk then 
            logger:info(string.format("The state.json file will be created in %s : (%s)",folderName, filePath))
            return filePath
        end
    end
    return nil
end

local function discoverDebriefingFilePath()   
    -- establish a search pattern into the following modes
    -- 1. Environment variable LIBERATION_EXPORT_DIR, to support dedicated server hosting
    -- 2. Embedded DCS Liberation dcsLiberation.installPath (set by the app to its install path), to support locally hosted single player
    -- 3. System temporary folder, as set in the TEMP environment variable
    -- 4. Working directory.
    
    local useCurrentStamping = nil
    if os then  
        useCurrentStamping = os.getenv("LIBERATION_EXPORT_STAMPED_STATE")
    end

    local installPath = nil
    if dcsLiberation then 
        installPath = dcsLiberation.installPath 
    end
    
    if os then
        local result = nil
        -- try using the LIBERATION_EXPORT_DIR environment variable
        result = testDebriefingFilePath(os.getenv("LIBERATION_EXPORT_DIR"), "LIBERATION_EXPORT_DIR", useCurrentStamping)
        if result then
            return result
        end
        -- no joy ? maybe there is a valid path in the mission ?
        result = testDebriefingFilePath(installPath, "the DCS Liberation install folder", useCurrentStamping)
        if result then
            return result
        end
        -- there's always the possibility of using the system temporary folder
        result = testDebriefingFilePath(os.getenv("TEMP"), "TEMP", useCurrentStamping)
        if result then
            return result
        end
    end

    -- nothing worked, let's try the last resort folder : current directory.
    if lfs then
        return testDebriefingFilePath(lfs.writedir().."Missions\\", "the working directory", useCurrentStamping)
    end
    
    return nil
end

debriefing_file_location = discoverDebriefingFilePath()

write_state_error_handling = function()
    local _debriefing_file_location = debriefing_file_location
    if not debriefing_file_location then 
        _debriefing_file_location = "[nil]"
        logger:error("Unable to find where to write DCS Liberation state")
    end
    write_success, return_value = pcall(write_state)
    if write_success then
    else
	    messageAll("Unable to write DCS Liberation state to ".._debriefing_file_location..
                "\nYou can abort the mission in DCS Liberation.\n"..
                "\n\nPlease fix your setup in DCS Liberation, make sure you are pointing to the right installation directory from the File/Preferences menu. Then after fixing the path restart DCS Liberation, and then restart DCS."..
                "\n\nYou can also try to fix the issue manually by replacing the file <dcs_installation_directory>/Scripts/MissionScripting.lua by the one provided there : <dcs_liberation_folder>/resources/scripts/MissionScripting.lua. And then restart DCS. (This will also have to be done again after each DCS update)"..
                "\n\nIt's not worth playing, the state of the mission will not be recorded.")
    end

    -- reschedule
    mist.scheduleFunction(write_state_error_handling, {}, timer.getTime() + WRITESTATE_SCHEDULE_IN_SECONDS)
end

function update_hit_points(event)
	local update = {}
	update.name = event.target:getName()
	get_life_success, update.hit_points = pcall(event.target.getLife, event.target)
	if get_life_success then
		unit_hit_point_updates[#unit_hit_point_updates + 1] = update
		write_state()
	end
end 

activeWeapons = {}
local function onEvent(event)

	simulation_time_seconds = event.time

    if event.id == world.event.S_EVENT_CRASH and event.initiator then
        crash_events[#crash_events + 1] = event.initiator.getName(event.initiator)
        write_state()
    end
   
    if event.id == world.event.S_EVENT_UNIT_LOST and event.initiator then
        unit_lost_events[#unit_lost_events + 1] = event.initiator.getName(event.initiator)
        write_state()
    end
	
	if event.id == world.event.S_EVENT_KILL and event.target then
        kill_events[#kill_events + 1] = event.target.getName(event.target)
        write_state()
    end

    if event.id == world.event.S_EVENT_DEAD and event.initiator then
	    get_initiator_name_success, initiator_name = pcall(event.initiator.getName, event.initiator)
		if get_initiator_name_success then
			dead_events[#dead_events + 1] = event.initiator.getName(event.initiator)
			local position = event.initiator.getPosition(event.initiator)
			local destruction = {}
			destruction.x = position.p.x
			destruction.y = position.p.y
			destruction.z = position.p.z
			destruction.type = event.initiator:getTypeName()
			destruction.orientation = mist.getHeading(event.initiator) * 57.3
			destroyed_objects_positions[#destroyed_objects_positions + 1] = destruction
			write_state()
		end
    end
	
	if event.id == world.event.S_EVENT_HIT then
        target_category = event.target:getCategory()
		if target_category == Object.Category.UNIT then
			-- check on the health of the target 1 second after as the life value is sometimes not updated
			-- at the time of the event
			timer.scheduleFunction(update_hit_points, event, timer.getTime() + 1)
		end
	end

    if event.id == world.event.S_EVENT_MISSION_END then
        mission_ended = true
        write_state()
    end

end

mist.addEventHandler(onEvent)

-- create the state.json file and start the scheduling
write_state_error_handling()