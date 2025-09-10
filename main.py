import logging
import datetime
from serial.tools.list_ports_linux import comports
from starlette.responses import HTMLResponse

from init_log import config_logging
# config_logging(logging.DEBUG if os.getenv('DEBUG') else logging.WARNING)

logging.basicConfig(level=logging.WARNING)

import argparse
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from vantage_pro2 import VantagePro2
from internal import Internal
from inside_arduino import InsideArduino
from outside_arduino import OutsideArduino
from cyclope import Cyclope
from tessw import TessW

from config.config import make_cfg, Config
from utils import ExtendedJSONResponse, SafetyResponse
from init_log import config_logging
from db_access import make_db_manager
from enum import Enum
from canonical import CanonicalResponse, CanonicalResponse_Ok


cfg: Config = make_cfg()
db_manager = make_db_manager()
stations: Dict[str, Any] = {}


name_to_class = {
    'internal': Internal,
    'davis': VantagePro2,
    'inside-arduino': InsideArduino,
    'outside-arduino': OutsideArduino,
    'cyclope': Cyclope,
    'tessw': TessW,
}


# logger: logging.Logger = logging.getLogger('main')
# init_log(logger)

ProjectName = Enum('ProjectName', {proj: proj for proj in cfg.projects})
StationName = Enum('StationName', {s: s for s in cfg.enabled_stations})


def make_stations():

    serial_ports = [c.device for c in comports()]

    for name in cfg.enabled_stations:
        constructor = name_to_class[name]
        station = constructor(name=name)

        for project in ['default'] + cfg.projects:
            # link the configured sensors to the station
            for sensor in cfg.sensors[project]:
                if sensor.settings.station == name:
                    station.sensors.append(sensor)

        # logger.debug(f"adding station '{name}'")
        stations[name] = station
        if hasattr(station, 'detect'):
            serial_ports = station.detect(serial_ports)  # returns a list without the used port
        stations[name].start()


@asynccontextmanager
async def lifespan(_):
    db_manager.connect()
    # db_manager.open_session()
    make_stations()
    yield
    # db_manager.close_session()
    db_manager.disconnect()
    for station in stations:
        stations[station].stop()

app = FastAPI(lifespan=lifespan, title="Safety at WAO (the Weizmann Astrophysical Observatory)")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"message": f"An exception occurred: {exc}"},
    )


@app.get("/config", tags=["info"])
async def show_configuration() -> CanonicalResponse:
    return CanonicalResponse(value=cfg)


@app.get("/stations", tags=["info"])
async def list_stations() -> CanonicalResponse:
    return CanonicalResponse(value={
        'known': list(cfg.toml['stations'].keys()),
        'enabled': cfg.enabled_stations,
        'in-use': cfg.stations_in_use,
    })


@app.get("/stations/{station}", tags=["info"], response_class=ExtendedJSONResponse)
async def get_station_details(station: StationName) -> CanonicalResponse:
    name = str(station).replace('StationName.', '')
    if name not in stations:
        # return JSONResponse({'msg': f"Bad station name '{name}'  Known stations: {list(stations.keys())}"})
        return CanonicalResponse(errors=[f"Bad station name '{name}'  Known stations: {list(stations.keys())}"])

    s = stations[name]
    return CanonicalResponse(value={
        'name': s.name,
        'settings': cfg.station_settings[name],
        'readings': s.readings
    })


@app.get("/{project}/sensors", tags=["info"], response_class=ExtendedJSONResponse)
async def get_sensors_for_specific_project(project: ProjectName) -> CanonicalResponse:
    from copy import deepcopy
    from utils import isoformat_zulu

    project_name = str(project).replace('ProjectName.', '')
    sensors = [deepcopy(sensor) for sensor in cfg.sensors[project_name]]

    for sensor in sensors:
        readings = sensor.readings
        if not isinstance(readings, list):
            readings = [readings]
        for reading in readings:
            reading.time = isoformat_zulu(reading.time)

    return CanonicalResponse(value={
        'project': project_name,
        'sensors': sensors,
    })

@app.get("/{project}/sensor/{sensor_name}", tags=["info"], response_class=ExtendedJSONResponse)
async def get_sensor_for_specific_project(project: ProjectName, sensor_name: str) -> CanonicalResponse:
    project_name = str(project).replace('ProjectName.', '')
    sensor = None
    found = [sensor for sensor in cfg.sensors[project_name] if sensor.name == sensor_name]
    if not found:
        project_sensors = [s.name for s in cfg.sensors[project_name]]
        return CanonicalResponse(errors=[f"no sensor named '{sensor_name}' for project '{project_name}' (sensors: {project_sensors})"])
    
    sensor =  found[0]
    station = stations[sensor.settings.station]
    
    from utils import isoformat_zulu
    from copy import copy

    s = copy(sensor)
    if not isinstance(s.readings, list):
        s.readings = [s.readings]
    for reading in s.readings:
        if isinstance(reading.time, datetime.datetime):
            reading.time = isoformat_zulu(reading.time)

    return CanonicalResponse(
        value={
            'project': project_name,
            'sensor': s,
            "interval": station.interval,
        })


@app.get("/{project}/is_safe", tags=["safety"], response_class=ExtendedJSONResponse)
async def get_project_specific_status(project: ProjectName) -> CanonicalResponse:
    name = str(project).replace('ProjectName.', '')

    return CanonicalResponse(value=is_safe(name))


@app.get("/is_safe", tags=["safety"], response_class=ExtendedJSONResponse)
async def get_global_status() -> CanonicalResponse:
    return CanonicalResponse(value=is_safe('default'))


@app.get("/human-intervention/create", tags=["human-intervention"])
async def create_human_intervention(reason: str) -> CanonicalResponse:
    internal: Internal = stations['internal']

    internal.human_intervention_file.create(reason)
    return CanonicalResponse_Ok


@app.get("/human-intervention/remove", tags=["human-intervention"])
async def remove_human_intervention() -> CanonicalResponse:
    internal: Internal = stations['internal']

    internal.human_intervention_file.remove()
    return CanonicalResponse_Ok

@app.get("/projects", tags=['Projects'])
async def projects() -> CanonicalResponse:

    return CanonicalResponse(value=cfg.projects)

@app.get("/help", tags=["Help"])
async def help():
    content = """
    <html>
        <head>
          <meta charset="UTF-8">
          <title>WAO Safety Daemon</title>
          <style>
            /* Optional: Add some basic table styling */
            table {
              border-collapse: collapse; /* Combine border lines */
              /* width: 50%;               /* Table width as a percentage of the page */
              margin: 20px 0;          /* Spacing above/below the table */
            }
            th, td {
              border: 1px solid #ccc;  /* Light gray border around cells */
              padding: 8px;            /* Spacing inside each cell */
              text-align: left;        /* Align text to the left */
            }
            th {
              background-color: #f2f2f2;  /* Slight background color for headers */
            }
            caption {
              caption-side: top;       /* Position caption at the top of the table */
              font-weight: bold;       /* Make caption text bold */
              margin-bottom: 8px;      /* Add space between caption and table */
            }
          </style>
        </head>
        <body>
            <table>
                <caption>WAO Safety Daemon Help</caption>
                <tr><th>URL</th><th>Description</th></tr>
                <tr><td><code>/config</code></td> <td>Dumps the whole configuration</td></tr>
                <tr><td><code>/stations</code></td><td>Lists the defined stations</td></tr>
                <tr><td><code>/projects</code></td><td>Lists the defined projects</td></tr>
                <tr><td><code>/stations/{<b>station</b>}</code></td><td>Dumps state of specified <code><b>station</b></code></td></tr>
                <tr><td><code>/{<b>project</b>}/sensors</code></td><td>Dumps state of the sensors for specified <code><b>project</b></code></td></tr>
                <tr><td><code>/{<b>project</b>}/sensor/{<b>sensor</b>}</code></td><td>Dumps state of the specified <b>sensor</b> for specified <code><b>project</b></code></td></tr>
                <tr><td>/<code>{<b>project</b>}/is_safe</code></td><td>Gets the specified <code><b>project</b></code>'s is_safe value</td></tr>
                <tr><td>/<code>is_safe</code></td><td>Gets the global is_safe value</td></tr>
                <tr><td><code>/human-intervention/create</code></td><td>Creates a site-wise human intervention state</td></tr>
                <tr><td><code>/human-intervention/remove</code></td><td>Removes the site-wise human intervention state</td></tr>                
            </table>
        </body>
    </html>
    """
    return HTMLResponse(content=content, status_code=200)

def is_safe(project: str) -> CanonicalResponse:
    if project is None:
        project = 'default'

    for station in stations:
        if hasattr(station, 'calculate_sensors'):
            station.calculate_sensors()

    ret = SafetyResponse()
    for sensor in cfg.sensors[project]:
        if not sensor.safe:
            ret.safe = False
            for reason in sensor.reasons_for_not_safe:
                ret.reasons.append(reason)
    return CanonicalResponse(value=ret)


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="A safety data-gathering daemon")
    parser.add_argument('-d', '--debug', action='store_true', help='Debug to stdout')

    args = parser.parse_args()
    config_logging(logging.DEBUG if args.debug else logging.INFO)

    svr = cfg.server
    uvicorn.run("main:app", host=svr.host, port=svr.port, reload=True)
