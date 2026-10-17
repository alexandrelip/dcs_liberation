from typing import Any

from dcs import task
from dcs.planes import F_5E_3, PlaneType

from game.modsupport import planemod


@planemod
class F_5EM(F_5E_3):
    id = "F-5EM"
    livery_name = "F-5E-3"
    payloads: dict[str, dict[str, Any]] = {}


@planemod
class AMX_M(PlaneType):
    id = "AMX_M"
    flyable = True
    height = 4.55
    width = 8.87
    length = 13.23
    fuel_max = 2790
    max_speed = 1051.2
    category = "Interceptor"
    radio_frequency = 127.5
    livery_name = "AMX_M"
    payloads: dict[str, dict[str, Any]] = {}
    pylons: set[int] = set()
    tasks = [
        task.SEAD,
        task.AntishipStrike,
        task.CAS,
        task.GroundAttack,
        task.PinpointStrike,
        task.RunwayAttack,
        task.AFAC,
        task.Escort,
        task.CAP,
        task.FighterSweep,
        task.Intercept,
    ]
    task_default = task.CAS


@planemod
class A_29B(PlaneType):
    id = "A-29B"
    flyable = True
    height = 3.97
    width = 11.14
    length = 11.38
    fuel_max = 800
    max_speed = 592.6
    category = "Interceptor"
    radio_frequency = 127.5
    livery_name = "A-29B"
    payloads: dict[str, dict[str, Any]] = {}
    pylons: set[int] = set()
    tasks = [
        task.CAS,
        task.GroundAttack,
        task.AFAC,
        task.PinpointStrike,
        task.RunwayAttack,
        task.AntishipStrike,
        task.Escort,
        task.CAP,
        task.FighterSweep,
        task.Intercept,
    ]
    task_default = task.CAS
