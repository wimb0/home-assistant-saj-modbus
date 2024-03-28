"""SAJ Modbus Hub"""
from pymodbus.register_read_message import ReadHoldingRegistersResponse
from pymodbus.register_write_message import ModbusResponse, WriteMultipleRegistersResponse
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from voluptuous.validators import Number
from homeassistant.helpers.typing import HomeAssistantType
import logging
import threading
from datetime import timedelta
from homeassistant.core import CALLBACK_TYPE, callback
from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException
from pymodbus.payload import BinaryPayloadDecoder

from .const import (
    DEVICE_STATUSSES,
    FAULT_MESSAGES,
)

_LOGGER = logging.getLogger(__name__)


class SAJModbusHub(DataUpdateCoordinator[dict]):
    """Thread safe wrapper class for pymodbus."""

    def __init__(
        self,
        hass: HomeAssistantType,
        name: str,
        host: str,
        port: Number,
        scan_interval: Number,
    ):
        """Initialize the Modbus hub."""
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=scan_interval),
        )

        self._client = ModbusTcpClient(host=host, port=port, timeout=5)
        self._lock = threading.Lock()

        self.inverter_data: dict = {}
        self.data: dict = {}
        self.limitpower: int = 100
        self.set_limitpower(100)

    @callback
    def async_remove_listener(self, update_callback: CALLBACK_TYPE) -> None:
        """Remove data update listener."""
        super().async_remove_listener(update_callback)

        """No listeners left then close connection"""
        if not self._listeners:
            self.close()

    def close(self) -> None:
        """Disconnect client."""
        with self._lock:
            self.set_limitpower(100)
            self._client.close()

    def _read_holding_registers(
        self, unit, address, count
    ) -> ReadHoldingRegistersResponse:
        """Read holding registers."""
        with self._lock:
            return self._client.read_holding_registers(address=address, count=count, slave=unit)

    def _write_registers(
        self, unit: int, address: int, values: list[int] | int
    ) -> ModbusResponse:
        """Write values to registers."""
        with self._lock:
            return self._client.write_registers(address=address, values=values, slave=unit)

    async def _async_update_data(self) -> dict:
        realtime_data = {}
        try:
            """Inverter info is only fetched once"""
            if not self.inverter_data:
                self.inverter_data = await self.hass.async_add_executor_job(
                    self.read_modbus_inverter_data
                )
            """Read realtime data"""
            realtime_data = await self.hass.async_add_executor_job(
                self.read_modbus_realtime_data
            )
        except ConnectionException:
            _LOGGER.error("Reading realtime data failed! Inverter is unreachable.")
            realtime_data["mpvmode"] = 0
            realtime_data["mpvstatus"] = DEVICE_STATUSSES[0]
            realtime_data["power"] = 0

        return {**self.inverter_data, **realtime_data}

    def read_modbus_inverter_data(self) -> dict:

        inverter_data = self._read_holding_registers(unit=1, address=0x8F00, count=29)

        if inverter_data.isError():
            return {}

        data = {}
        decoder = BinaryPayloadDecoder.fromRegisters(
            inverter_data.registers, byteorder=Endian.BIG
        )

        devtype = decoder.decode_16bit_uint()
        data["devtype"] = devtype
        subtype = decoder.decode_16bit_uint()
        data["subtype"] = subtype
        commver = decoder.decode_16bit_uint()
        data["commver"] = round(commver * 0.001, 3)

        sn = decoder.decode_string(20).decode("ascii")
        data["sn"] = str(sn)
        pc = decoder.decode_string(20).decode("ascii")
        data["pc"] = str(pc)

        dv = decoder.decode_16bit_uint()
        data["dv"] = round(dv * 0.001, 3)
        mcv = decoder.decode_16bit_uint()
        data["mcv"] = round(mcv * 0.001, 3)
        scv = decoder.decode_16bit_uint()
        data["scv"] = round(scv * 0.001, 3)
        disphwversion = decoder.decode_16bit_uint()
        data["disphwversion"] = round(disphwversion * 0.001, 3)
        ctrlhwversion = decoder.decode_16bit_uint()
        data["ctrlhwversion"] = round(ctrlhwversion * 0.001, 3)
        powerhwversion = decoder.decode_16bit_uint()
        data["powerhwversion"] = round(powerhwversion * 0.001, 3)

        return data

    def read_modbus_realtime_data(self) -> dict:

        realtime_data = self._read_holding_registers(unit=1, address=0x100, count=60)

        if realtime_data.isError():
            return {}

        data = {}

        decoder = BinaryPayloadDecoder.fromRegisters(
            realtime_data.registers, byteorder=Endian.BIG
        )

        mpvmode = decoder.decode_16bit_uint()
        data["mpvmode"] = mpvmode

        if mpvmode in DEVICE_STATUSSES:
            data["mpvstatus"] = DEVICE_STATUSSES[mpvmode]
        else:
            data["mpvstatus"] = "Unknown"

        faultMsg0 = decoder.decode_32bit_uint()
        faultMsg1 = decoder.decode_32bit_uint()
        faultMsg2 = decoder.decode_32bit_uint()

        faultMsg = []
        faultMsg.extend(
            self.translate_fault_code_to_messages(faultMsg0, FAULT_MESSAGES[0].items())
        )
        faultMsg.extend(
            self.translate_fault_code_to_messages(faultMsg1, FAULT_MESSAGES[1].items())
        )
        faultMsg.extend(
            self.translate_fault_code_to_messages(faultMsg2, FAULT_MESSAGES[2].items())
        )

        # status value can hold max 255 chars in HA
        data["faultmsg"] = ", ".join(faultMsg).strip()[0:254]
        if faultMsg:
            _LOGGER.error("Fault message: " + ", ".join(faultMsg).strip())

        pv1volt = decoder.decode_16bit_uint()
        pv1curr = decoder.decode_16bit_uint()
        pv1power = decoder.decode_16bit_uint()
        data["pv1volt"] = round(pv1volt * 0.1, 1)
        data["pv1curr"] = round(pv1curr * 0.01, 2)
        data["pv1power"] = round(pv1power * 1, 0)

        pv2volt = decoder.decode_16bit_uint()
        pv2curr = decoder.decode_16bit_uint()
        pv2power = decoder.decode_16bit_uint()
        data["pv2volt"] = round(pv2volt * 0.1, 1)
        data["pv2curr"] = round(pv2curr * 0.01, 2)
        data["pv2power"] = round(pv2power * 1, 0)

        pv3volt = decoder.decode_16bit_uint()
        pv3curr = decoder.decode_16bit_uint()
        pv3power = decoder.decode_16bit_uint()
        data["pv3volt"] = round(pv3volt * 0.1, 1)
        data["pv3curr"] = round(pv3curr * 0.01, 2)
        data["pv3power"] = round(pv3power * 1, 0)

        busvolt = decoder.decode_16bit_uint()
        data["busvolt"] = round(busvolt * 0.1, 1)

        invtempc = decoder.decode_16bit_int()
        data["invtempc"] = round(invtempc * 0.1, 1)

        gfci = decoder.decode_16bit_int()
        data["gfci"] = gfci

        power = decoder.decode_16bit_uint()
        data["power"] = power

        qpower = decoder.decode_16bit_int()
        data["qpower"] = qpower

        pf = decoder.decode_16bit_int()
        data["pf"] = round(pf * 0.001, 3)

        l1volt = decoder.decode_16bit_uint()
        l1curr = decoder.decode_16bit_uint()
        l1freq = decoder.decode_16bit_uint()
        l1dci = decoder.decode_16bit_int()
        l1power = decoder.decode_16bit_uint()
        l1pf = decoder.decode_16bit_int()
        data["l1volt"] = round(l1volt * 0.1, 1)
        data["l1curr"] = round(l1curr * 0.01, 2)
        data["l1freq"] = round(l1freq * 0.01, 2)
        data["l1dci"] = l1dci
        data["l1power"] = l1power
        data["l1pf"] = round(l1pf * 0.001, 3)

        l2volt = decoder.decode_16bit_uint()
        l2curr = decoder.decode_16bit_uint()
        l2freq = decoder.decode_16bit_uint()
        l2dci = decoder.decode_16bit_int()
        l2power = decoder.decode_16bit_uint()
        l2pf = decoder.decode_16bit_int()
        data["l2volt"] = round(l2volt * 0.1, 1)
        data["l2curr"] = round(l2curr * 0.01, 2)
        data["l2freq"] = round(l2freq * 0.01, 2)
        data["l2dci"] = l2dci
        data["l2power"] = l2power
        data["l2pf"] = round(l2pf * 0.001, 3)

        l3volt = decoder.decode_16bit_uint()
        l3curr = decoder.decode_16bit_uint()
        l3freq = decoder.decode_16bit_uint()
        l3dci = decoder.decode_16bit_int()
        l3power = decoder.decode_16bit_uint()
        l3pf = decoder.decode_16bit_int()
        data["l3volt"] = round(l3volt * 0.1, 1)
        data["l3curr"] = round(l3curr * 0.01, 2)
        data["l3freq"] = round(l3freq * 0.01, 2)
        data["l3dci"] = l3dci
        data["l3power"] = l3power
        data["l3pf"] = round(l3pf * 0.001, 3)

        iso1 = decoder.decode_16bit_uint()
        iso2 = decoder.decode_16bit_uint()
        iso3 = decoder.decode_16bit_uint()
        iso4 = decoder.decode_16bit_uint()
        data["iso1"] = iso1
        data["iso2"] = iso2
        data["iso3"] = iso3
        data["iso4"] = iso4

        todayenergy = decoder.decode_16bit_uint()
        monthenergy = decoder.decode_32bit_uint()
        yearenergy = decoder.decode_32bit_uint()
        totalenergy = decoder.decode_32bit_uint()
        data["todayenergy"] = round(todayenergy * 0.01, 2)
        data["monthenergy"] = round(monthenergy * 0.01, 2)
        data["yearenergy"] = round(yearenergy * 0.01, 2)
        data["totalenergy"] = round(totalenergy * 0.01, 2)

        todayhour = decoder.decode_16bit_uint()
        data["todayhour"] = round(todayhour * 0.1, 1)
        totalhour = decoder.decode_32bit_uint()
        data["totalhour"] = round(totalhour * 0.1, 1)

        errorcount = decoder.decode_16bit_uint()
        data["errorcount"] = errorcount

        return data

    def translate_fault_code_to_messages(
        self, fault_code: int, fault_messages: list
    ) -> list:
        messages = []
        if not fault_code:
            return messages

        for code, mesg in fault_messages:
            if fault_code & code:
                messages.append(mesg)

        return messages

    def set_limitpower(self, value: int):
        """Limit the power output of the inverter."""
        response = self._write_registers(unit=1, address=0x801F, values=int(value*10))
        if not isinstance(response, WriteMultipleRegistersResponse):
            raise response
        self.limitpower = value
        self.hass.add_job(self.async_update_listeners)

    def set_value(self, key: str, value: int):
        """Set value matching key."""
        if key == "limitpower":
            self.set_limitpower(value)
