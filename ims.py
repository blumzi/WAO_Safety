from station import IPStation
import httpx
from enum import Enum
import logging
import datetime
import time
from typing import List, Optional
import json
from pydantic import BaseModel, validate_model

from init_log import init_log
from utils import ImsReading, ImsDatum
from sqlalchemy.orm import scoped_session
from config.config import Config
from db_access import DbManager

logger = logging.getLogger('ims')
init_log(logger)

class ImsChannel(BaseModel):
    id: int
    name: str
    alias: Optional[str] = None
    value: float
    status: int
    valid: bool
    description: Optional[str]

class Ims(IPStation):

    cover: float

    def __init__(self, name: str):

        super().__init__(name)
        cfg = Config()
        self.station_id = self.name.replace("ims", "")
        self.cfg = cfg.toml['stations'][self.name]
        self.interval = cfg.station_settings[self.name].interval
        self.db_manager = DbManager()

    def datums(self) -> List[str]:
        return [item.value for item in ImsDatum]

    def fetcher(self):

        url = f"https://{self.host}/v1/envista/stations/{self.station_id}/data/latest"
        try:
            response = httpx.request(
                method="GET",
                url=url,
                proxy="http://bcproxy.weizmann.ac.il:8080",
                timeout=20,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": "ApiToken 1a901e45-9028-44ff-bd2c-35e82407fb9b"
                    }
            )
            response.raise_for_status()
        except Exception as ex:
            logger.debug(f"{self.name}:fetcher: exception {ex} (url={url})")
            return

        try:
            json_response = response.content.decode("utf-8", errors="replace")
            ims_response = json.loads(json_response)
            channels = ims_response["data"][0]["channels"]
        except Exception as ex:
            logger.error(f"{self.name}: could not get data, {ex=}")
            return
        
        reading: ImsReading = ImsReading()
        for channel in channels:
            if not channel["valid"]:
                continue
            if channel["name"] == "Rain":
                reading.datums[ImsDatum.RainRate] = channel["value"]
            elif channel["name"] == "RH":
                reading.datums[ImsDatum.Humidity] = channel["value"]
            elif channel["name"] == "WS":
                reading.datums[ImsDatum.WindSpeed] = channel["value"]
            elif channel["name"] == "WD":
                reading.datums[ImsDatum.WindDirection] = channel["value"]
            elif channel["name"] == "TD":
                reading.datums[ImsDatum.Temperature] = channel["value"]
        reading.tstamp = datetime.datetime.utcnow()


        with self.lock:
            self.readings.push(reading)
        if hasattr(self, 'saver'):
            self.saver(reading)

    def latest_readings(self, datum: str, n: int = 1) -> list:
        return self.readings[-n:] if n < len(self.readings) else self.readings

    def saver(self, reading: ImsReading) -> None:
        from db_access import Ims232DbClass

        ims232 = Ims232DbClass(
            temperature=reading.datums[ImsDatum.Temperature],
            humidity=reading.datums[ImsDatum.Humidity],
            wind_speed=reading.datums[ImsDatum.WindSpeed],
            wind_direction=reading.datums[ImsDatum.WindDirection],
            rain_rate=reading.datums[ImsDatum.RainRate],
            tstamp=reading.tstamp,
        )

        logger.info(f"{self.name}:saver: saving {reading.datums=}")

        Session = scoped_session(self.db_manager.session_factory)
        session = Session()
        try:
            session.add(ims232)
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            Session.remove()

    def calculate_sensors(self):
        pass


if __name__ == "__main__":
    ims232 = Ims('ims232')
    ims232.fetcher()
    print(f"{ims232.latest_readings()=}")
