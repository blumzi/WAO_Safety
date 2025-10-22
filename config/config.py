import logging
from typing import List, Dict
from copy import deepcopy

import tomlkit

# from init_log import init_log
from sensor import Sensor, MinMaxSettings, HumanInterventionSettings, SunElevationSettings
from utils import split_source, SunElevationSensorName, HumanInterventionSensorName

logger: logging.Logger = logging.getLogger('config')
# init_log(logger)


class StationSettings:
    enabled: bool
    interval: int  # seconds
    nreadings: int
    datums: List[str]

    def __init__(self, d: dict):
        self.enabled = d['enabled'] if 'enabled' in d else False
        self.interval = d['interval'] if 'interval' in d else 60
        self.nreadings = d['nreadings'] if 'nreadings' in d else 1
        self.datums = d['datums']


class SerialStationSettings(StationSettings):

    serial: str
    baud: int
    timeout: float
    write_timeout: float

    def __init__(self, d: dict):
        super().__init__(d)
        self.serial = d['serial']
        self.baud = d['baud']
        if 'timeout' in d:
            self.timeout = float(d['timeout'])
        self.write_timeout = float(d['write-timeout']) if 'write-timeout' in d else 2.0


class HttpStationSettings(StationSettings):

    host: str
    port: int

    def __init__(self, d):
        super().__init__(d)
        self.host = d['host']
        self.port = int(d['port']) if "port" in d else None


class StationConfig:
    name: str
    settings: StationSettings


class LocationConfig:
    longitude: float
    latitude: float
    elevation: float

    def __init__(self, d: dict):
        self.longitude = d['longitude']
        self.latitude = d['latitude']
        self.elevation = d['elevation']


class ServerConfig:
    host: str
    port: int

    def __init__(self, d: dict):
        self.host = d['host']
        self.port = d['port']


class DatabaseConfig:
    host: str
    name: str
    user: str
    password: str
    schema: str

    def __init__(self, d: dict):
        self.host = d['host']
        self.name = d['name']
        self.user = d['user']
        self.password = d['password']
        self.schema = d['schema']


class Config:
    _instance = None
    _initialized = False

    filename: str
    toml: dict
    projects: List[str]
    station_settings: Dict[str, StationSettings]
    enabled_stations: List[str]
    sensors: Dict[str, List[Sensor]]
    enabled_sensors: List[str]
    stations_in_use: List[str]

    database: DatabaseConfig
    location: LocationConfig
    server: ServerConfig

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.projects = list()
        self.station_settings = dict()
        self.sensors = {'default': list()}
        self.stations_in_use = list()
        self.toml = {}
        self.enabled_stations = list()
        self.filename = 'config/safety.toml'

        with open(self.filename, 'r') as file:
            self.toml = deepcopy(tomlkit.load(file))

        self.database = DatabaseConfig(self.toml['database'])
        self.server = ServerConfig(self.toml['server'])
        self.location = LocationConfig(self.toml['location'])

        for name in list(self.toml['stations'].keys()):
            if 'serial' in self.toml['stations'][name]:
                self.station_settings[name] = SerialStationSettings(self.toml['stations'][name])
            elif 'host' in self.toml['stations'][name]:
                self.station_settings[name] = HttpStationSettings(self.toml['stations'][name])
            else:
                self.station_settings[name] = StationSettings(self.toml['stations'][name])

        for key in self.station_settings.keys():
            if self.station_settings[key].enabled:
                self.enabled_stations.append(key)

        for ll in [self.station_settings.keys(), self.enabled_stations, self.stations_in_use]:
            if 'internal' not in ll:
                ll.insert(0, 'internal')

        self.projects = self.toml['global']['projects']
        for project_name in self.projects:
            self.sensors[project_name] = list()

        for sensor_name in self.toml['sensors']:
            # scan the 'default' sensors
            settings_dict = self.toml['sensors'][sensor_name]
            enabled = settings_dict['enabled'] if 'enabled' in settings_dict else False
            if not enabled:
                logger.debug(f"project 'default': skipping '{sensor_name}' (not enabled)")
                continue
            station_name, datum = split_source(settings_dict['source'])
            if station_name not in self.station_settings:
                raise Exception(f"Bad station name '{station_name}' for sensor '{sensor_name}'. " +
                                f"Known station names are: {', '.join(self.station_settings)}")
            if datum not in self.station_settings[station_name].datums:
                raise Exception(f"Bad sensor '{sensor_name}': Invalid datum '{datum}' for station '{station_name}' " +
                                f"(valid datums: {self.station_settings[station_name].datums})")
            settings_dict['station'] = station_name
            settings_dict['datum'] = datum
            if station_name not in self.enabled_stations:
                settings_dict['enabled'] = False
                logger.debug(f"project: 'default': skipping '{sensor_name}' (station '{station_name}' not enabled)")
                continue

            if sensor_name == SunElevationSensorName:
                settings = SunElevationSettings(settings_dict)
            elif sensor_name == HumanInterventionSensorName:
                settings = HumanInterventionSettings(settings_dict)
            else:
                settings = MinMaxSettings(settings_dict)

            settings.project = 'default'
            new_sensor = Sensor(
                name=sensor_name,
                settings=settings,
            )
            logger.debug(f"project: 'default', adding '{new_sensor.name}'")
            self.sensors['default'].append(new_sensor)

        # copy all default sensors to the projects
        for project in self.projects:
            self.sensors[project] = deepcopy(self.sensors['default'])
            for s in self.sensors[project]:
                s.settings.project = project

        # look for project-specific sensors and override them
        for project in self.projects:
            if project in self.toml and 'sensors' in self.toml[project]:
                for sensor_name in self.toml[project]['sensors']:
                    project_dict = self.toml[project]['sensors'][sensor_name]
                    sensor = [s for s in self.sensors[project] if s.name == sensor_name]
                    if len(sensor) > 0:  # this sensor is one of the default sensors
                        sensor = sensor[0]
                        sensor.settings.__dict__.update(project_dict)
                        if sensor.settings.enabled:
                            if sensor.settings.station not in self.enabled_stations:
                                logger.debug(f"sensor '{sensor.name}' (project '{project}') was disabled " +
                                            f"(station '{sensor.settings.station}' is disabled)'")
                                sensor.settings.enabled = False
                    else:  # this sensor is defined for this project only
                        if sensor_name == SunElevationSensorName:
                            settings = SunElevationSettings(project_dict)
                        elif sensor_name == HumanInterventionSensorName:
                            settings = HumanInterventionSettings(project_dict)
                        else:
                            settings = MinMaxSettings(project_dict)
                        # self.sensors[project].append(
                        #     Sensor(name=project_dict['name'], settings=settings))

        # make a list of all the station which are enabled and used by at least one sensor
        for project in ['default'] + self.projects:
            for s in self.sensors[project]:
                if not s.settings.enabled:
                    continue
                if s.settings.station not in self.enabled_stations:
                    s.settings.enabled = False
                    continue
                if s.settings.station not in self.stations_in_use:
                    self.stations_in_use.append(s.settings.station)

        self._initialized = True
        # self.dump()

    def dump(self):
        print("")
        print("station_settings:")
        print(f"  all:     {list(self.station_settings.keys())}")
        print(f"  enabled: {self.enabled_stations}")
        print(f"  in use:  {self.stations_in_use}")
        print("")
        print("sensors (per project):")
        print("")
        for project in ['default'] + self.projects:
            for sensor_setting in self.sensors[project]:
                print(f"  {project:8s} {sensor_setting}")
            print()


def make_cfg():
    return Config()


if __name__ == "__main__":
    cfg = make_cfg()
    cfg.dump()
