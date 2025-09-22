def pause_print(plugin):
    if not plugin._printer.is_printing():
        return {"error": "현재 프린트 중이 아닙니다"}
    try:
        plugin._printer.pause_print(tags={"source:plugin"})
        return {"success": True, "message": "프린트 일시정지"}
    except Exception as e:
        return {"error": f"일시정지 실패: {str(e)}"}


def resume_print(plugin):
    if not plugin._printer.is_paused():
        return {"error": "현재 일시정지 상태가 아닙니다"}
    try:
        plugin._printer.resume_print(tags={"source:plugin"})
        return {"success": True, "message": "프린트 재개"}
    except Exception as e:
        return {"error": f"재개 실패: {str(e)}"}


def cancel_print(plugin):
    if not (plugin._printer.is_printing() or plugin._printer.is_paused()):
        return {"error": "현재 프린트 중이거나 일시정지 상태가 아닙니다"}
    try:
        plugin._printer.cancel_print(tags={"source:plugin"})
        return {"success": True, "message": "프린트 취소"}
    except Exception as e:
        return {"error": f"취소 실패: {str(e)}"}


def home_axes(plugin, axes):
    if not plugin._printer.is_operational():
        return {"error": "프린터가 연결되지 않았습니다"}
    try:
        plugin._printer.home(axes, tags={"source:plugin"})
        return {"success": True, "message": f"홈킹 시작: {axes}"}
    except Exception as e:
        return {"error": f"홈킹 실패: {str(e)}"}



def move_axes(plugin, mode="relative", x=None, y=None, z=None, e=None, feedrate=1000):
    """
    대시보드 수동 이동. 기본은 상대좌표(G91)로 이동 후 복구(G90).
    mode: 'relative' | 'absolute'
    feedrate: mm/min
    """
    try:
        if not plugin._printer.is_operational():
            return {"error": "프린터가 연결되지 않았습니다"}

        if all(v is None for v in (x, y, z, e)):
            return {"error": "이동할 축 값이 없습니다"}

        use_relative = (str(mode or "relative").lower() != "absolute")

        commands = []
        if use_relative:
            commands.append("G91")  # 상대좌표

        parts = []
        if x is not None: parts.append(f"X{float(x)}")
        if y is not None: parts.append(f"Y{float(y)}")
        if z is not None: parts.append(f"Z{float(z)}")
        if e is not None: parts.append(f"E{float(e)}")
        f = float(feedrate or 1000)
        parts.append(f"F{int(f)}")
        commands.append("G1 " + " ".join(parts))

        if use_relative:
            commands.append("G90")  # 절대좌표 복구

        try:
            plugin._printer.commands(commands, tags={"source:plugin", "mqtt:control"})
        except TypeError:
            plugin._printer.commands(commands)

        return {"success": True, "message": "이동 명령 전송", "commands": commands}
    except Exception as e:
        return {"error": f"이동 실패: {str(e)}"}


def set_temperature(plugin, tool: int, temperature: float, wait: bool = False):
    try:
        if not plugin._printer.is_operational():
            return {"error": "프린터가 연결되지 않았습니다"}

        commands = []
        temp_value = float(temperature)

        if int(tool) == -1:
            # 베드
            cmd = f"{'M190' if wait else 'M140'} S{int(temp_value)}"
            commands.append(cmd)
        else:
            extruder_index = int(tool)
            # 필요 시 활성 툴 전환
            commands.append(f"T{extruder_index}")
            if wait:
                commands.append(f"M109 S{int(temp_value)} T{extruder_index}")
            else:
                commands.append(f"M104 S{int(temp_value)} T{extruder_index}")

        try:
            plugin._printer.commands(commands, tags={"source:plugin", "mqtt:control"})
        except TypeError:
            plugin._printer.commands(commands)

        return {"success": True, "message": "온도 설정 명령 전송", "commands": commands}
    except Exception as e:
        return {"error": f"온도 설정 실패: {str(e)}"}

