from typing import Optional

from sqlalchemy import create_engine, MetaData, Engine
from sqlalchemy.ext.automap import automap_base
# from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from config.config import make_cfg
from utils import VantageProReading, VantageProDatum
from utils import InsideArduinoReading, InsideArduinoDatum
from utils import OutsideArduinoReading, OutsideArduinoDatum
from utils import TessWReading, TessWDatum
from utils import ImsDatum, ImsReading

Base = None
DavisDbClass = None
ArduinoInDbClass = None
ArduinoOutDbClass = None
TessWDbClass = None
Ims232DbClass = None


class DbManager:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(DbManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        cfg = make_cfg()
        conf = cfg.database
        self.schema = conf.schema
        self.url = f"postgresql://{conf.user}:{conf.password}@{conf.host}/{conf.name}"

        # self.session: Optional[Session] = None
        self.session_factory = None
        self.metadata: Optional[MetaData] = None
        self.engine: Optional[Engine] = None

        self.ArduinoIn = None
        self.Vantage = None
        self.TessW = None
        self.Ims232 = None
        self.Base = None
        self._initialized = True

    def connect(self):
        global Base, DavisDbClass, ArduinoInDbClass, ArduinoOutDbClass, TessWDbClass, Ims232DbClass

        self.engine = create_engine(self.url, echo=False)
        self.session_factory = sessionmaker(bind=self.engine)

        Base = automap_base()
        Base.prepare(autoload_with=self.engine, schema=self.schema)

        DavisDbClass = Base.classes.davis
        ArduinoInDbClass = Base.classes.arduino_in
        ArduinoOutDbClass = Base.classes.arduino_out
        TessWDbClass = Base.classes.tessw
        Ims232DbClass = Base.classes.ims232

    def disconnect(self):
        if self.engine is not None:
            self.engine.dispose()

    def close_session(self):
        if hasattr(self, 'session'):
            self.session.close()

    def __del__(self):
        self.close_session()
        self.disconnect()

    def write_vantage_measurement(self, reading: VantageProReading):
        davis = DavisDbClass(
            temp_in=reading.datums[VantageProDatum.InsideTemperature],
            humidity_in=reading.datums[VantageProDatum.InsideHumidity],
            pressure_out=reading.datums[VantageProDatum.Barometer],
            temp_out=reading.datums[VantageProDatum.OutsideTemperature],
            humidity_out=reading.datums[VantageProDatum.OutSideHumidity],
            wind_speed=reading.datums[VantageProDatum.WindSpeed],
            wind_direction=reading.datums[VantageProDatum.WindDirection],
            rain=reading.datums[VantageProDatum.RainRate],
            solar_radiation=reading.datums[VantageProDatum.SolarRadiation],
            tstamp=reading.tstamp,
        )

        self.session.add(davis)
        self.session.commit()

    def write_arduino_in_measurement(self, reading: InsideArduinoReading):
        arduino_in = ArduinoInDbClass(
            presence=reading.datums[InsideArduinoDatum.Presence],
            temp_in=reading.datums[InsideArduinoDatum.TemperatureIn],
            pressure_in=reading.datums[InsideArduinoDatum.PressureIn],
            visible_lux_in=reading.datums[InsideArduinoDatum.VisibleLuxIn],
            flame=reading.datums[InsideArduinoDatum.Flame],
            co2=reading.datums[InsideArduinoDatum.CO2],
            voc=reading.datums[InsideArduinoDatum.VOC],
            raw_h2=reading.datums[InsideArduinoDatum.RawH2],
            raw_ethanol=reading.datums[InsideArduinoDatum.RawEthanol],
            tstamp=reading.tstamp,
        )

        self.session.add(arduino_in)
        self.session.commit()

    def write_arduino_out_measurement(self, reading: OutsideArduinoReading):
        arduino_out = ArduinoOutDbClass(
            temp_out=reading.datum[OutsideArduinoDatum.TemperatureOut],
            humidity_out=reading.datum[OutsideArduinoDatum.HumidityOut],
            pressure_out=reading.datum[OutsideArduinoDatum.PressureOut],
            dew_point=reading.datum[OutsideArduinoDatum.DewPoint],
            visible_lux_out=reading.datum[OutsideArduinoDatum.VISIBLE_LUX_OUT],
            ir_luminosity=reading.datum[OutsideArduinoDatum.IrLuminosity],
            wind_speed=reading.datum[OutsideArduinoDatum.WindSpeed],
            wind_direction=reading.datum[OutsideArduinoDatum.WindDirection],
            tstamp=reading.tstamp
        )

        self.session.add(arduino_out)
        self.session.commit()

    def write_tessw_measurement(self, reading: TessWReading):
        tessw = TessWDbClass(
            cover=reading.datum[TessWDatum.CloudCover],
            tstamp=reading.tstamp
        )

        self.session.add(tessw)
        self.session.commit()

    def write_ims232_measurement(self, reading: ImsReading):
        ims232 = Ims232DbClass(
            temp=reading.datum[ImsDatum.Temperature],
            humidity=reading.datum[ImsDatum.Humidity],
            wind_speed=reading.datum[ImsDatum.WindSpeed],
            wind_direction=reading.datum[ImsDatum.WindDirection],
            rain=reading.datum[ImsDatum.RainRate],
            tstamp=reading.tstamp
        )

        self.session.add(ims232)
        self.session.commit()


def make_db_manager():
    return DbManager()
