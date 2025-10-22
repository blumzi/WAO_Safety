import json
import os.path
from threading import Timer, Event
import datetime
from json import JSONEncoder
from fastapi.responses import JSONResponse
from typing import Any, NamedTuple, List
from enum import Enum

default_port = 8000
Never = datetime.datetime.min

SunElevationSensorName = "sun"
HumanInterventionSensorName = "human-intervention"


class SafetyResponse:
    """
    The response from a **Sensor** when asked if it is is_safe
    """
    safe: bool          # Is it is_safe?
    reasons: List[str]  # Why it is *unsafe*

    def __init__(self, safe: bool = True, reasons: List[str] = None):
        self.safe = safe
        self.reasons = reasons if reasons is not None else list()


class RepeatTimer(Timer):
    def __init__(self, name, interval, function):
        super(RepeatTimer, self).__init__(interval=interval, function=function)
        self.name = name
        self.interval = interval
        self.function = function
        self.stopped = Event()

    def run(self):
        while not self.stopped.wait(self.interval):
            self.function(*self.args, **self.kwargs)

    def stop(self):
        self.stopped.set()


class FixedSizeFifo:
    def __init__(self, max_size: int):
        self.max_size = max_size
        self.data = []

    def push(self, item):
        if len(self.data) >= self.max_size:
            self.data.pop(0)
        self.data.append(item)

    def latest(self):
        return self.data[0]

    def get(self):
        return self.data


def isoformat_zulu(dt: datetime.datetime) -> str:
    """
    Returns an ISO-8601 formatted string with a 'Z' suffix for UTC datetimes
    :param dt: The datetime to format
    :return: The ISO-8601 formatted string
    """
    if not hasattr(dt, "tzinfo") or dt.tzinfo is None:
        return dt.isoformat() + "Z"
    elif dt.tzinfo.utcoffset(dt) == datetime.timedelta(0):
        return dt.replace(tzinfo=None).isoformat() + "Z"
    else:
        return dt.isoformat()


def fromisoformat_zulu(s: str) -> datetime.datetime:
    """
    Parses an ISO-8601 formatted string with optional 'Z' suffix for UTC datetimes
    :param s: The ISO-8601 formatted string
    :return: The corresponding datetime
    """
    if s.endswith("Z"):
        s = s[:-1]
        return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc)
    else:
        return datetime.datetime.fromisoformat(s)

# class SingletonFactory:
#     _instances = {}
#     _lock = Lock()  # A lock for synchronizing instance creation
#
#     @classmethod
#     def get_instance(cls, class_type, *args, **kwargs):
#         with cls._lock:
#             if class_type not in cls._instances:
#                 cls._instances[class_type] = class_type(*args, **kwargs)
#         return cls._instances[class_type]


class DateTimeEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return None if obj == Never else isoformat_zulu(obj)
        # Let the base class default method raise the TypeError
        return JSONEncoder.default(self, obj)


def datetime_decoder(dct):
    for key, value in dct.items():
        if isinstance(value, str):
            try:
                dct[key] = fromisoformat_zulu(value)
            except ValueError:
                pass  # Not a datetime string, so we leave it unchanged
    return dct


class ExtendedJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=DateTimeEncoder).encode('utf-8')


class Source(NamedTuple):
    station: str
    datum: str


def split_source(source: str) -> NamedTuple:
    s = source.split(':')
    return Source(s[0], s[1])


class Singleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Singleton, cls).__new__(cls)
        return cls._instance


class Reading:
    datums: dict
    tstamp: datetime.datetime

    def __init__(self):
        self.datums = dict()


class ImsDatum(str, Enum):
    WindDirection = "wind_direction"
    WindSpeed = "wind_speed"
    Humidity = "humidity"
    RainRate = "rain_rate"
    Temperature = "temperature"

    @classmethod
    def datums(cls):
        return [item.value for item in cls]

class ImsReading(Reading):
    def __init__(self):
        super().__init__()
        for name in ImsDatum.datums():
            self.datums[name] = None

class VantageProDatum(str, Enum):
    Barometer = "barometer",
    InsideTemperature = "inside_temperature",
    InsideHumidity = "inside_humidity",
    OutsideTemperature = "outside_temperature",
    WindSpeed = "wind_speed",
    WindDirection = "wind_direction",
    OutSideHumidity = "outside_humidity",
    RainRate = "rain_rate",
    UV = "uv",
    SolarRadiation = "solar_radiation",

    @classmethod
    def datums(cls):
        return [item.value for item in cls]


class VantageProReading(Reading):
    def __init__(self):
        super().__init__()
        for name in VantageProDatum.datums():
            self.datums[name] = None

class TessWReading(Reading):
    def __init__(self):
        super().__init__()
        for name in TessWDatum.names():
            self.datums[name] = None

class OutsideArduinoDatum(str, Enum):
    TemperatureOut = "temperature_out",
    HumidityOut = "humidity_out",
    PressureOut = "pressure_out",
    DewPoint = "dew_point",
    VisibleLuxOut = "visible_lux_out",
    IrLuminosity = "ir_luminosity",
    WindSpeed = "wind_speed",
    WindDirection = "wind_direction",

    @classmethod
    def names(cls) -> list:
        return [item.value for item in cls]


class OutsideArduinoReading(Reading):
    def __init__(self):
        super().__init__()
        for name in OutsideArduinoDatum.names():
            self.datums[name] = None


class TessWDatum(str, Enum):
    CloudCover = "cover",

    @classmethod
    def names(cls) -> list:
        return [item.value for item in cls]


class TessWReading(Reading):
    def __init__(self):
        super().__init__()
        for name in TessWDatum.names():
            self.datums[name] = None

class InsideArduinoDatum(str, Enum):
    TemperatureIn = "temperature_in",
    PressureIn = "pressure_in",
    VisibleLuxIn = "visible_lux_in",
    Presence = "presence",
    Flame = "flame",
    CO2 = "co2",
    RawH2 = "raw_h2",
    RawEthanol = "raw_ethanol",
    VOC = "voc",

    @classmethod
    def names(cls) -> list:
        return [item.value for item in cls]


class InsideArduinoReading(Reading):
    def __init__(self):
        super().__init__()
        for name in InsideArduinoDatum.names():
            self.datums[name] = None


class HumanInterventionFileContent:
    reason: str
    tstamp: datetime.datetime


class HumanIntervention:
    filename: str

    def __init__(self, human_intervention_file: str):
        self.filename = human_intervention_file

    def is_safe(self) -> SafetyResponse:
        response = SafetyResponse()
        if os.path.exists(self.filename):
            response.safe = False
            with open(self.filename) as f:
                content = json.load(f)
            response.reasons.append(f"sensor 'human-intervention', reason='{content['reason']}', " +
                                    f"from={content['tstamp']}")
        return response

    def create(self, reason: str):
        with open(self.filename, 'w') as file:
            json.dump({
                'tstamp': datetime.datetime.now(),
                'reason': reason
            }, file, indent=2, cls=DateTimeEncoder)

    def remove(self):
        os.remove(self.filename)


def formatted_float_list(readings: list, fmt: str = ".2f") -> str:
    try:
        formatted_values = [f"{reading.value:{fmt}}" for reading in readings]
        formatted_values = '[' + ", ".join(formatted_values) + ']'
    except TypeError as e:
        print(f"{e}")

    return formatted_values
