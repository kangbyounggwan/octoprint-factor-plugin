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


