import time
from abc import ABC, abstractmethod
from typing import Tuple, Union

from serial_weather_device import SerialWeatherDevice
from my_parser import Parser


class QueryWeatherArduino(SerialWeatherDevice, ABC):
    """
    This is a base class for several similar Arduino devices.
    All devices that inherit from this class are devices with this API:

    PC: <measurement name>?
    ARDUINO: <some text><value 1><some text><value 2><some text>
    """
    def __init__(self, ser):
        super().__init__(ser)

    def _query(self, param_name: str, wait: float) -> str:
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        request_txt = f"{param_name}?\r\n"

        print(f" * QueryWeatherArduino._query * sending {request_txt}")

        self.ser.write(request_txt.encode("utf-8"))
        time.sleep(wait)

        response_txt =  self.ser.readline().decode("utf-8")

        while response_txt == request_txt:
            response_txt =  self.ser.readline().decode("utf-8")

        return response_txt

    def _send_and_parse_query(self, parma_name, wait: float, format_str: str) -> Tuple[Union[int, float]]:
        response = self._query(parma_name, wait)
        print("_send_and_parse_query!!!!")
        print(f"!!!! format   : {format_str}|")
        print(f"!!!! response : {response}|")

        return Parser.parse(format_str, response)

    @abstractmethod
    def get_correct_file(self) -> str:
        pass

    def check_right_port(self) -> bool:
        print(" * QueryWeatherArduino.check_right_port * checking if arduino is connected correctly")
        response = self._query("id", 0.5)
        print(f" * QueryWeatherArduino.check_right_port * recieved {response}")
        

        return self.get_correct_file() in response

