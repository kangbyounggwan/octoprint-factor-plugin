def pause_print(plugin):
    if not plugin._printer.is_printing():
        return {"error": "Not currently printing"}
    try:
        plugin._printer.pause_print(tags={"source:plugin"})
        return {"success": True, "message": "Print paused"}
    except Exception as e:
        return {"error": f"Pause failed: {str(e)}"}


def resume_print(plugin):
    if not plugin._printer.is_paused():
        return {"error": "Not currently paused"}
    try:
        plugin._printer.resume_print(tags={"source:plugin"})
        return {"success": True, "message": "Print resumed"}
    except Exception as e:
        return {"error": f"Resume failed: {str(e)}"}


def cancel_print(plugin):
    if not (plugin._printer.is_printing() or plugin._printer.is_paused()):
        return {"error": "Not currently printing or paused"}
    try:
        plugin._printer.cancel_print(tags={"source:plugin"})
        return {"success": True, "message": "Print cancelled"}
    except Exception as e:
        return {"error": f"Cancel failed: {str(e)}"}


def home_axes(plugin, axes):
    if not plugin._printer.is_operational():
        return {"error": "Printer not connected"}
    try:
        plugin._printer.home(axes, tags={"source:plugin"})
        return {"success": True, "message": f"Homing started: {axes}"}
    except Exception as e:
        return {"error": f"Homing failed: {str(e)}"}



def move_axes(plugin, mode="relative", x=None, y=None, z=None, e=None, feedrate=1000):
    """
    Manual axis movement from dashboard. Default is relative coordinates (G91) with restore (G90).
    mode: 'relative' | 'absolute'
    feedrate: mm/min
    """
    try:
        if not plugin._printer.is_operational():
            return {"error": "Printer not connected"}

        if all(v is None for v in (x, y, z, e)):
            return {"error": "No axis values to move"}

        use_relative = (str(mode or "relative").lower() != "absolute")

        commands = []
        if use_relative:
            commands.append("G91")  # Relative positioning

        parts = []
        if x is not None: parts.append(f"X{float(x)}")
        if y is not None: parts.append(f"Y{float(y)}")
        if z is not None: parts.append(f"Z{float(z)}")
        if e is not None: parts.append(f"E{float(e)}")
        f = float(feedrate or 1000)
        parts.append(f"F{int(f)}")
        commands.append("G1 " + " ".join(parts))

        if use_relative:
            commands.append("G90")  # Restore absolute positioning

        try:
            plugin._printer.commands(commands, tags={"source:plugin", "mqtt:control"})
        except TypeError:
            plugin._printer.commands(commands)

        return {"success": True, "message": "Move command sent", "commands": commands}
    except Exception as e:
        return {"error": f"Move failed: {str(e)}"}


def set_temperature(plugin, tool: int, temperature: float, wait: bool = False):
    try:
        if not plugin._printer.is_operational():
            return {"error": "Printer not connected"}

        commands = []
        temp_value = float(temperature)

        if int(tool) == -1:
            # Bed
            cmd = f"{'M190' if wait else 'M140'} S{int(temp_value)}"
            commands.append(cmd)
        else:
            extruder_index = int(tool)
            # Switch active tool if needed
            commands.append(f"T{extruder_index}")
            if wait:
                commands.append(f"M109 S{int(temp_value)} T{extruder_index}")
            else:
                commands.append(f"M104 S{int(temp_value)} T{extruder_index}")

        try:
            plugin._printer.commands(commands, tags={"source:plugin", "mqtt:control"})
        except TypeError:
            plugin._printer.commands(commands)

        return {"success": True, "message": "Temperature command sent", "commands": commands}
    except Exception as e:
        return {"error": f"Temperature setting failed: {str(e)}"}


def set_feed_rate(plugin, factor: float):
    """
    Set feed rate (speed) factor.
    factor: Percentage (100 = 100%, 50 = 50%, 200 = 200%)
    G-code: M220 S<factor>
    """
    try:
        if not plugin._printer.is_operational():
            return {"error": "Printer not connected"}

        factor_value = float(factor)
        if factor_value < 10 or factor_value > 500:
            return {"error": "Feed rate must be between 10% and 500%"}

        commands = [f"M220 S{int(factor_value)}"]

        try:
            plugin._printer.commands(commands, tags={"source:plugin", "mqtt:control"})
        except TypeError:
            plugin._printer.commands(commands)

        return {"success": True, "message": f"Feed rate set to {int(factor_value)}%", "commands": commands}
    except Exception as e:
        return {"error": f"Feed rate setting failed: {str(e)}"}


def set_fan_speed(plugin, speed: int):
    """
    Set fan speed.
    speed: 0-255 (0 = off, 255 = full speed)
    Percentage can also be used (0-100, will be converted to 0-255)
    G-code: M106 S<speed> or M107 (fan off)
    """
    try:
        if not plugin._printer.is_operational():
            return {"error": "Printer not connected"}

        speed_value = int(speed)

        # If value is 0-100, assume percentage and convert to 0-255
        if 0 <= speed_value <= 100:
            pwm_value = int((speed_value / 100.0) * 255)
        elif 101 <= speed_value <= 255:
            pwm_value = speed_value
        else:
            return {"error": "Fan speed must be between 0-255"}

        commands = []
        if pwm_value == 0:
            commands.append("M107")  # Fan off
        else:
            commands.append(f"M106 S{pwm_value}")  # Set fan speed

        try:
            plugin._printer.commands(commands, tags={"source:plugin", "mqtt:control"})
        except TypeError:
            plugin._printer.commands(commands)

        return {"success": True, "message": f"Fan speed set to {pwm_value}/255", "commands": commands}
    except Exception as e:
        return {"error": f"Fan speed setting failed: {str(e)}"}

