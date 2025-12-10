import struct

# ==============================================================================
# 1. HELPER FUNCTIONS
# ==============================================================================

def parse_le_int16(data, offset=0):
    """Little Endian: Byte[0] is LSB (Used by Inverter)"""
    if len(data) < offset + 2: return 0
    raw = data[offset] | (data[offset+1] << 8)
    if raw > 32767: raw -= 65536 
    return raw

def parse_be_int16(data, offset=0):
    """Big Endian: Byte[0] is HSB (Used by UI Voltages)"""
    if len(data) < offset + 2: return 0
    raw = (data[offset] << 8) | data[offset+1]
    if raw > 32767: raw -= 65536
    return raw

def parse_ivt_int40(data):
    """Custom IVT Sensor Format: 5 Bytes, Big Endian"""
    if len(data) < 6: return 0
    raw = (data[1] << 32) | (data[2] << 24) | (data[3] << 16) | (data[4] << 8) | data[5]
    if raw & 0x8000000000: 
        raw -= 0x10000000000
    return raw

# ==============================================================================
# 2. DECODING LOGIC
# ==============================================================================

def decode_inverter_multiplexed(data):
    if len(data) < 3: return {"Error": "Len<3"}
    mux_id = data[0]
    raw_val = parse_le_int16(data, 1)

    if mux_id == 0x30:   return {"RPM": raw_val * 1.0}
    elif mux_id == 0xEB: return {"DC Bus": raw_val * 0.1}
    elif mux_id == 0x20: return {"Inv Current": raw_val * 0.1}
    elif mux_id == 0x49: return {"Motor Temp": raw_val * 1.0}
    elif mux_id == 0x4A: return {"IGBT Temp": raw_val * 1.0}
    else: return {f"Mux {hex(mux_id)}": raw_val}

def decode_inverter_igbt_temp(data):
    return {"IGBT Temp (L)": parse_le_int16(data, 1) * 1.0}

def decode_torque_command(data):
    return {"Torque Cmd": parse_le_int16(data, 1)}

def decode_ui_voltages(data):
    return {
        "UI V1": parse_be_int16(data, 2) * 0.01,
        "UI V2": parse_be_int16(data, 4) * 0.01,
        "UI V3": parse_be_int16(data, 6) * 0.01
    }

def decode_ui_temperatures(data):
    if len(data) < 7: return {"Error": "Short"}
    return {"UI T1": data[2], "UI T2": data[3], "UI T3": data[4]}

# IVT Sensors
def decode_ivt_current(d):         return {"Current": f"{parse_ivt_int40(d) * 0.001:.2f} A"}
def decode_ivt_voltage_vehicle(d): return {"Volts Veh": f"{parse_ivt_int40(d) * 0.001:.2f} V"}
def decode_ivt_voltage_pack(d):    return {"Volts Pack": f"{parse_ivt_int40(d) * 0.001:.2f} V"}
def decode_ivt_wattage(d):         return {"Power": f"{parse_ivt_int40(d) * 1.0:.1f} W"}
def decode_ivt_current_counter(d): return {"Ah": parse_ivt_int40(d) * 1.0}
def decode_ivt_wattage_counter(d): return {"Wh": parse_ivt_int40(d) * 1.0}

# Status Flags
def decode_acu_info_1(data):    return {"ACU Info 1": bytes(data).hex()}
def decode_acu_info_2(data):    return {"ACU Info 2": bytes(data).hex()}
def decode_acu_precharge(data): return {"Precharge": data[0]}
def decode_vcu_connected(data): return {"VCU": bool(data[0])}
def decode_vcu_reply(data):     return {"VCU Reply": bool(data[0])}

# ==============================================================================
# 3. REGISTRY & CLASS
# ==============================================================================

CAN_ID_NAMES = {
    0x181: "Inverter Status (Mux)",
    0x385: "Inverter IGBT Temp",
    0x201: "Torque Command",
    0x700: "UI Voltages",
    0x701: "UI Temps",
    0x521: "IVT Current",
    0x522: "IVT Voltage Veh",
    0x523: "IVT Voltage Pack",
    0x100: "ACU Control"
}

DECODER_MAP = {
    0x181: decode_inverter_multiplexed, 
    0x385: decode_inverter_igbt_temp,   
    0x201: decode_torque_command,       
    0x700: decode_ui_voltages,
    0x701: decode_ui_temperatures,
    0x105: decode_acu_info_1,           
    0x106: decode_acu_info_2,           
    0x100: decode_acu_precharge,        
    0x521: decode_ivt_current,
    0x522: decode_ivt_voltage_vehicle,
    0x523: decode_ivt_voltage_pack,
    0x526: decode_ivt_wattage,
    0x527: decode_ivt_current_counter,
    0x528: decode_ivt_wattage_counter,
    0x175: decode_vcu_connected,
    0x176: decode_vcu_reply
}

class DataDecoder:
    def decode(self, can_id_str, data_bytes_list):
        """Converts Hex ID and Byte List into Engineering Values"""
        try:
            can_id = int(can_id_str, 16)
            data_ints = [int(x, 16) for x in data_bytes_list]
            
            decoder_func = DECODER_MAP.get(can_id)
            if decoder_func:
                return decoder_func(data_ints)
            else:
                return "No Decoder"
        except Exception as e:
            return f"Err: {str(e)}"

    def get_name(self, can_id_str):
        try:
            cid = int(can_id_str, 16)
            return CAN_ID_NAMES.get(cid, "Unknown ID")
        except:
            return "Unknown"