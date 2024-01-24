import datetime
from typing import List

from station import Reading, SerialStation
from enum import Enum
import logging
from utils import SingletonFactory
from config.config import cfg
from init_log import init_log
from arduino import Arduino


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


class OutsideArduino(SerialStation, Arduino):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(self.name)
        init_log(self.logger)
        try:
            super().__init__(name=self.name)
        except Exception as ex:
            self.logger.error(f"Cannot construct SerialStation for '{self.name}'", exc_info=ex)
            return

        config = cfg.get(f"stations.{self.name}")
        self.interval = config['interval'] if 'interval' in config else 60

        from db_access import DbManager
        self.db_manager = SingletonFactory.get_instance(DbManager)
        self.db_manager.connect()
        self.db_manager.open_session()

    @classmethod
    def datums(cls) -> List[str]:
        return [item.value for item in OutsideArduinoDatum]

    def fetcher(self) -> None:
        reading: OutsideArduinoReading = OutsideArduinoReading()

        try:
            self.get_wind(reading)
            self.get_light(reading)
            self.get_pressure_humidity_temperature(reading)
        except Exception as ex:
            self.logger.error(f"Failed to get readings", exc_info=ex)
            return

        reading.tstamp = datetime.datetime.utcnow()
        self.readings.push(reading)
        if hasattr(self, 'saver'):
            self.saver(reading)

    def saver(self, reading: OutsideArduinoReading) -> None:
        from db_access import ArduinoOutDbClass

        arduino_out = ArduinoOutDbClass(
            temp_out=reading.datums[OutsideArduinoDatum.TemperatureOut],
            humidity_out=reading.datums[OutsideArduinoDatum.HumidityOut],
            pressure_out=reading.datums[OutsideArduinoDatum.PressureOut],
            dew_point=reading.datums[OutsideArduinoDatum.DewPoint],
            visible_lux_out=reading.datums[OutsideArduinoDatum.VisibleLuxOut],
            ir_luminosity=reading.datums[OutsideArduinoDatum.IrLuminosity],
            wind_speed=reading.datums[OutsideArduinoDatum.WindSpeed],
            wind_direction=reading.datums[OutsideArduinoDatum.WindDirection],
            tstamp=reading.tstamp
        )

        self.db_manager.session.add(arduino_out)
        self.db_manager.session.commit()

    def get_wind(self, reading: OutsideArduinoReading):
        wind_results = self.query("wind", 0.05, "v={f} m/s  dir. {f}°")

        reading.datums[OutsideArduinoDatum.WindSpeed] = wind_results[0]
        reading.datums[OutsideArduinoDatum.WindDirection] = wind_results[1]

    def get_light(self, reading: OutsideArduinoReading):
        light_results = self.query("light", 0.08, "TSL vis(Lux) IR(luminosity): {i} {i}")

        reading.datums[OutsideArduinoDatum.VisibleLuxOut] = light_results[0]
        reading.datums[OutsideArduinoDatum.IrLuminosity] = light_results[1]

    def get_pressure_humidity_temperature(self, reading: OutsideArduinoReading):
        results = self.query("pht", 0.08, "P:{f}hPa T:{f}°C RH:{f}% comp RH:{f}% dew point:{f}°C")

        reading.datums[OutsideArduinoDatum.PressureOut] = results[0]
        reading.datums[OutsideArduinoDatum.TemperatureOut] = results[1]
        reading.datums[OutsideArduinoDatum.HumidityOut] = results[2]
        reading.datums[OutsideArduinoDatum.DewPoint] = results[3]

    def get_correct_file(self) -> str:
        return "Outdoor_multiQuery.ino"
