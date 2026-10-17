# Turnless Campaign

This outlines a path for us converting Liberation from turn based into a
turnless campaign game like BMS.

## Hard problems

### We can't simulate combat

We can't feasibly simulate the details of combat, nor can we generate a mission
mid-engagement. The mission editor does not support generating aircraft
mid-maneuver, or with any SA.

To avoid that problem, instead of simulating the combat we put the group in a
"freeze" at the moment the engagement begins. Any frozen groups are spawned
wherever they were frozen so simulation can be deferred to DCS. Each freeze will
have a deadline for completion, at which point a simple strength-based
autoresolve will take place.

After a frozen engagement is resolved (whether in sim or automatically), if the
mission objective has not been achieved a mission abort will be evaluated.

### We don't know where the roads are

We don't know where the in-game roads are, so we can't precisely simulate the
location of convoys as they move, nor the amount of time they will take to move
between bases.

Time can be solved by just having the campaign designer encode the travel time
in the campaign. The ME will estimate it for them so it’s simple to do. Spawn
locations cannot be made precise, but we can have campaign designers define
several waypoints along the route and spawn the convoy at the most appropriate
one.

### SAM engagement zones are huge

The large threat zone of many SAMs would cause most of the map to be a frozen
engagement.

To avoid that, SAMs will not cause frozen engagements, but will be simulated at
a basic level. Each SAM will track a group, and when in range will periodically
“shoot”, and those shots will have a chance to kill an aircraft in the targeted
group.

## Systems that need to change

### AI Commander

Theater state tracking for the HTN becomes much more complicated since it needs
to always be able to replan based on pending plans. This shouldn't be too bad
since RndName's PR did similar and the plan to continue that should work here.
The commander needs to learn to abort missions that are no longer viable.

### Transports

With turns gone, transports can longer move one link per turn. See the entry in
"hard problems" above. To begin with we can pick an arbitrary time per link and
just always spawn the transport at the origin regardless of where they ought to
be.

### Turn based systems

A number of systems that act in a number of turns become time based:

- Runway repair
- Unit delivery
- Weather changes
- Pilot replenishment
- Income

Procurement could be made simpler if we do away with cash in favor of fixed
replenishment rates.

### Front line advancement

Front line combat is happening continuously so we need to simulate its movement
and losses on the front line.

### Mission generation

The mission generator needs to be able to generate aircraft in specific
locations, with partial fuel, and possibly with some weapons expended.

### Mission result processing

Last known positions need to be recorded, as do weapon inventory and fuel
states.

### UI

Frozen combats need to be immutable to the player.

Missions in progress need to be made cancelable.

The map needs to show the locations of in-progress missions, including frozen
engagements.

There needs to be a UI to examine frozen engagements.

## Roadmap

This roadmap is ordered so that we can attempt to make this change in phases
that may take more than a single release. It is not focused on providing the
best gameplay experience ASAP, but on being able to approach this gradually
rather than freezing all other development or branching and a painful merge.

### Phase-one implementation status

Turnless mode now advances a persistent campaign progression clock and
deterministically ordered event queue while strategic simulation time moves.
The time-based systems are:

- coalition income paid for each completed six-hour campaign period;
- transfer progress, deliveries, and pilot replenishment every six hours;
- route-length-based convoy and cargo-ship ETAs checked every five minutes;
- airlift delivery when the transport flight completes its planned route;
- deterministic stance- and force-based ground attrition every 30 minutes;
- DCS-exported aircraft position, altitude, fuel, health, airborne state, and
  aggregate ammunition;
- damage-adjusted aircraft turnaround;
- periodic invalidation of impossible unlaunched packages;
- automatic two-aircraft QRA within 100 NM of threatened friendly bases;
- deterministic capability-based air and SAM autoresolve;
- strategic capture of land airfields and FOBs by continuous ground offensives;
- a bounded campaign history exposed in the map UI and local API;
- persistent transactional squadron weapon stores with compatible fallbacks;
- nine player-configurable HTN theater-priority categories;
- a default mission-performance bubble that culls distant units and omits
  untasked inventory aircraft from DCS while retaining them in campaign state;
- weather and front-line recovery every six hours;
- configurable periodic ATO replanning during live strategic fast-forward; and
- configurable aircraft turnaround after completed flights.

Legacy turn-based campaigns retain end-of-turn income and immediate aircraft
availability. Replaying elapsed time from a completed DCS mission consumes ATO
replanning intervals, but planning runs once after the replay rather than
creating missions retroactively.

Continuous ground combat updates losses and FLOT position but deliberately does
not capture control points yet. Capture requires additional handling for
retreating units, aircraft, ground-object ownership, IADS, and mission
invalidation.

Exact survivor position, altitude, and fuel are used when another mission is
generated immediately. If strategic simulation advances again, the exact
snapshot is invalidated and the flight-plan estimate becomes authoritative.
Damage affects maintenance duration but cannot be reproduced visually in a
generated mission. Aggregate ammunition is retained for later logistics work;
individual pylon reconstruction is not yet supported.

Reactive ATO updates preserve every package that has begun execution. Unlaunched
packages are removed when their target, ownership, or departure runway makes
them impossible, allowing the theater commander to replace them. QRA currently
uses proximity rather than sensor-level detection, and airborne retasking
remains future work.

Air and SAM autoresolve now use reproducible capability scoring rather than
global random coin flips. Ground offensives can capture land airfields and
FOBs through the same ownership, retreat, redeployment, and IADS paths used by
DCS debriefing. Strategic events are retained in a bounded history and shown
in the map UI. Individual rounds inside multi-weapon racks, sensor geometry,
and geographic PAK priorities are not yet modeled.

Squadron stores are reserved as a transaction before mission generation and
refunded if generation fails or an unlaunched flight is cancelled. Continued
flights reuse their reservation. Store quantities currently count pylon CLSIDs,
which may represent multi-round racks. Theater priorities reorder or disable
the commander's global HTN action categories; geographic PAK weighting remains
future work.

Mission generation now enables the existing objective-distance culling bubble
for new campaigns and does not render untasked squadron inventory on ramps by
default. The inventory remains fully available to the ATO and can be rendered
again with the mission-generator performance setting. Land-based AI flights are
late-activated at their scheduled startup time by default rather than existing
as uncontrolled ramp aircraft for the entire mission. Objective vehicle and
ship groups are also late-activated when an active air, land, or sea unit enters
their configurable bubble, expanded where necessary to cover a threat's weapon
range. Activation is one-way for the current DCS mission. Fragged packages and
units inside active objective bubbles still run in DCS.

The performance profile also caps MIST's scheduler at 15 Hz and rotates eligible
ground and non-carrier naval controllers through a 15% active cohort. Skynet
contact evaluation uses the same budget. This is a concurrency and update-rate
budget, not an operating-system CPU quota. Aircraft controllers are not paused
in flight; aircraft CPU load is bounded through scheduled late activation.

The default tactical layer is bounded per coalition to three SAM sites, six
helicopters, fifteen front-line vehicles, five infantry, twenty combat
aircraft, one tanker, one AEW&C aircraft, one carrier, and six other ships.
Player packages are admitted first and act as deaggregation anchors. Excess AI
flights and ground forces remain in the campaign model, where elapsed DCS time
and capability-based autoresolve advance them without instantiating additional
DCS AI. The limits are ceilings: unavailable or unplanned asset categories are
not filled with invented units.

Both sides use an aggressive ground posture by default. Generated mobile armor
and infantry receive routes toward the nearest enemy control point, while the
continuous campaign resolver moves the FLOT and can capture connected land
bases between DCS missions.

### Front-line progress rework

Add auto-resolve for the front line, adjust progress estimates based on stances
and not just kills (an enemy in retreat is less likely to be killed, but still
gives up ground).

### Add play from first-contact option

Add simulation of the mission from the start of the turn up to the first
engagement. Generate the mission from that point.

### Add fuel expenditure estimation for travel to start location

Adjust fuel quantities at the start of the mission to account for travel.

### Add UI to display simulation to first contact

Before removing turns, add play/pause buttons to the game that will simulate the
mission up to the first engagement. Once play is pressed no changes may be made
to the ATO.

When the turn ends it behaves like the normal end of turn. The ATO is reset and
the new turn is planned.

### Add mission abort option for players

Add the option to abort flight and packages for players. The AI won’t use this
yet but it will be needed once engagement simulation is added.

### Add simulation for frozen combats

Allows play to proceed through engagements. The AI will abort missions that are
unlikely to succeed after each combat is resolved.

### Estimate fuel/weapon use simulation for frozen combats

Improve behavior for groups that have completed an auto-resolved combat by
estimating their fuel and ammo use. This could be used to check if the mission
should be aborted.

### Add player options to create new packages after pressing play

Allow players to create new flights as the mission simulates. This would be the
most effective way to add intercept missions.

### Make planning real-time

Make the AI planner periodically reevaluate missions to add to the ATO. It will
still plan as many missions as possible up front so that the DCS side of the
mission can run as long as possible, but it could make use of aircraft that had
aborted or returned.

### Time-based systems instead of turn based

Move the systems that are currently based on turns to be based on duration. Each
turn is assumed to be six hours since there are four turns in a day.

### Time between turns based on mission duration

Change the turn duration to be based on the length of the mission played.

### Track end positions of aircraft, remove turns

If we can track the status of missions after the simulation ends we can continue
where we left off. Do that, and remove the concept of turns.

### Track ammo/fuel status of aircraft at the end of the mission

Improve post-simulation realism by tracking the ammunition and fuel spent.

### Add turnaround times for landed aircraft

Once aircraft returning from a mission land, a timer starts to track the
turnaround time before they'll be ready to redeploy as opposed to being instant.