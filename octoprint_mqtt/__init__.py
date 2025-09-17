# -*- coding: utf-8 -*-
import json
from flask import request  # Blueprint에서 사용
import octoprint.plugin
from octoprint.util import RepeatedTimer



__plugin_name__ = "MQTT-Plugin from FACTOR"
__plugin_pythoncompat__ = ">=3.8,<4"
__plugin_version__ = "1.0.9"
__plugin_identifier__ = "factor_mqtt"

class MqttPlugin(octoprint.plugin.SettingsPlugin,
                 octoprint.plugin.AssetPlugin,
                 octoprint.plugin.TemplatePlugin,
                 octoprint.plugin.StartupPlugin,
                 octoprint.plugin.ShutdownPlugin,
                 octoprint.plugin.EventHandlerPlugin,
                 octoprint.plugin.BlueprintPlugin):
    
    def __init__(self):
        super().__init__()
        self.mqtt_client = None
        self.is_connected = False
        self._snapshot_timer = None
    
    ##~~ SettingsPlugin mixin
    
    def get_settings_defaults(self):
        return dict(
            broker_host="localhost",
            broker_port=1883,
            broker_username="",
            broker_password="",
            topic_prefix="octoprint",   # JS와 일치!
            qos_level=0,
            retain_messages=False,
            publish_status=True,
            publish_progress=True,
            publish_temperature=True,
            publish_gcode=False,
            publish_snapshot=True,
            periodic_interval=1.0
            
        )
    
    def get_settings_version(self):
        return 1
    
    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._disconnect_mqtt()
        self._connect_mqtt()
        # 타이머는 연결 성공 시 자동으로 시작됨
    
    ##~~ AssetPlugin mixin
    
    def get_assets(self):
        return dict(
            js=["js/mqtt.js"],
            css=["css/mqtt.css"]
        )
    
    ##~~ TemplatePlugin mixin
    def on_startup(self, host, port):
        self._connect_mqtt()
        try:
            self._log_api_endpoints(host, port)
        except Exception as e:
            self._logger.warning("엔드포인트 로그 중 오류: %s", e)
    
    def on_after_startup(self):
        """시작 후 초기화 작업"""
        # 더 이상 busy-wait 금지. 필요하면 그냥 타이머를 미리 켜두고
        # tick에서 is_connected를 확인하게 해도 됩니다.
        pass


    # --- 여기부터 유틸 메서드 추가 ---
    def _log_api_endpoints(self, host: str, port: int):
        """
        플러그인 로드 시 접근 가능한 API 엔드포인트를 콘솔(octoprint.log)에 출력
        """
        # reverse proxy 등으로 baseUrl 이 설정된 경우 고려
        base_url = self._settings.global_get(["server", "baseUrl"]) or ""
        base_url = base_url.rstrip("/")

        # 실제로 바인딩된 내부 주소 기준 (OctoPrint 서비스 관점)
        internal_base = f"http://{host}:{port}{base_url}"
        pid = __plugin_identifier__

        status_url = f"{internal_base}/api/plugin/{pid}/status"
        test_url   = f"{internal_base}/api/plugin/{pid}/test"

        self._logger.info("[FACTOR MQTT] REST endpoints ready:")
        self._logger.info(" - GET  %s", status_url)
        self._logger.info(" - POST %s", test_url)
        self._logger.info("   (헤더 'X-Api-Key' 필요)")

    def get_template_configs(self):
        return [dict(
            type="settings",
            name="FACTOR MQTT",
            template="mqtt_settings.jinja2",
            custom_bindings=True   # ← 여기 꼭 True
        )]
    
    
    ##~~ ShutdownPlugin mixin
    
    def on_shutdown(self):
        self._disconnect_mqtt()
    
    ##~~ EventHandlerPlugin mixin
    
    def on_event(self, event, payload):
        if not self.is_connected:
            return
        
        topic_prefix = self._settings.get(["topic_prefix"])
        
        if event == "PrinterStateChanged":
            self._publish_status(payload, topic_prefix)
        elif event == "PrintProgress":
            self._publish_progress(payload, topic_prefix)
        elif event == "TemperatureUpdate":
            self._publish_temperature(payload, topic_prefix)
        elif event == "GcodeReceived":
            self._publish_gcode(payload, topic_prefix)
    
    ##~~ Private methods
    
    def _connect_mqtt(self):
        try:
            import paho.mqtt.client as mqtt
            
            self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            
            # 인증 정보 설정
            username = self._settings.get(["broker_username"])
            password = self._settings.get(["broker_password"])
            if username:
                self.mqtt_client.username_pw_set(username, password)
            
            # 콜백 함수 설정
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_publish = self._on_mqtt_publish
            self.mqtt_client.on_log = self._on_mqtt_log
            
            # 재연결 설정
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)
            
            # 비동기 연결
            host = self._settings.get(["broker_host"])
            port = int(self._settings.get(["broker_port"]))
            self._logger.info(f"MQTT 비동기 연결 시도: {host}:{port}")
            
            # connect_async로 비동기 연결 시작
            self.mqtt_client.connect_async(host, port, 60)
            self.mqtt_client.loop_start()
            
        except Exception as e:
            self._logger.error(f"MQTT 연결 실패: {e}")
    
    def _disconnect_mqtt(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            self.mqtt_client = None
            self.is_connected = False
            self._logger.info("MQTT 클라이언트 연결이 종료되었습니다.")
    
    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None, *args, **kwargs):
        self.is_connected = (rc == 0)
        if self.is_connected:
            self._logger.info("MQTT 브로커 연결 OK")
            self._start_snapshot_timer()     # ✅ 여기서 시작
        else:
            self._logger.error(f"MQTT 연결 실패 rc={rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc, properties=None, *args, **kwargs):
        self.is_connected = False
        self._logger.warning(f"MQTT 연결 끊김 rc={rc}")
        # 타이머는 유지해도 되고 멈춰도 됨. 유지하면 재연결 후 자동 퍼블리시됨.
        # 멈추고 싶다면 아래 주석 해제:
        # self._stop_snapshot_timer()
    
    def _on_mqtt_publish(self, client, userdata, mid, properties=None):
        self._logger.debug(f"MQTT 메시지 발행 완료. 메시지 ID: {mid}")
    
    def _on_mqtt_log(self, client, userdata, level, buf):
        """MQTT 로그 콜백 - 연결 상태 디버깅용"""
        if level == 1:  # DEBUG level
            self._logger.debug(f"MQTT: {buf}")
        elif level == 2:  # INFO level
            self._logger.info(f"MQTT: {buf}")
        elif level == 4:  # WARNING level
            self._logger.warning(f"MQTT: {buf}")
        elif level == 8:  # ERROR level
            self._logger.error(f"MQTT: {buf}")
    
    def _check_mqtt_connection_status(self):
        """MQTT 연결 상태를 확인합니다."""
        if not self.mqtt_client:
            return False
        
        try:
            # 연결 상태 확인
            if self.mqtt_client.is_connected():
                return True
            else:
                # 연결되지 않은 경우 로그만 출력 (재연결은 자동으로 처리됨)
                self._logger.debug("MQTT 연결이 끊어져 있습니다.")
                return False
        except Exception as e:
            self._logger.error(f"MQTT 연결 상태 확인 중 오류: {e}")
            return False
    
    def _publish_status(self, payload, topic_prefix):
        if not self._settings.get(["publish_status"]):
            return
        
        import json
        topic = f"{topic_prefix}/status"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_progress(self, payload, topic_prefix):
        if not self._settings.get(["publish_progress"]):
            return
        
        import json
        topic = f"{topic_prefix}/progress"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_temperature(self, payload, topic_prefix):
        if not self._settings.get(["publish_temperature"]):
            return
        
        import json
        topic = f"{topic_prefix}/temperature"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_gcode(self, payload, topic_prefix):
        if not self._settings.get(["publish_gcode"]):
            return
        
        import json
        topic = f"{topic_prefix}/gcode"
        message = json.dumps(payload)
        self._publish_message(topic, message)
    
    def _publish_message(self, topic, message):
        if not self.is_connected or not self.mqtt_client:
            return
        
        try:
            import paho.mqtt.client as mqtt
            qos = self._settings.get(["qos_level"])
            retain = self._settings.get(["retain_messages"])
            result = self.mqtt_client.publish(topic, message, qos=qos, retain=retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self._logger.debug(f"메시지 발행 성공: {topic}")
            else:
                self._logger.error(f"메시지 발행 실패: {topic}, 오류 코드: {result.rc}")
                
        except Exception as e:
            self._logger.error(f"메시지 발행 중 오류 발생: {e}")
    
    ##~~ BlueprintPlugin mixin
    
    @octoprint.plugin.BlueprintPlugin.route("/status", methods=["GET"])
    def get_mqtt_status(self):
        """MQTT 연결 상태를 반환합니다."""
        return {
            "connected": self.is_connected,
            "broker_host": self._settings.get(["broker_host"]),
            "broker_port": self._settings.get(["broker_port"])
        }
        
    @octoprint.plugin.BlueprintPlugin.route("/test", methods=["POST"])
    def test_mqtt_connection(self):
        import time, json, threading
        import paho.mqtt.client as mqtt

        data = request.get_json(force=True, silent=True) or {}
        host = data.get("broker_host", "localhost")
        port = int(data.get("broker_port", 1883))
        username = data.get("broker_username")
        pw = data.get("broker_password", "")
        do_publish = bool(data.get("publish", False))
        topic = data.get("test_topic") or f"{self._settings.get(['topic_prefix']) or 'octoprint'}/test"

        self._logger.info("[TEST] MQTT 연결 테스트 시작 host=%s port=%s user=%s pw=%s publish=%s topic=%s",
                        host, port, (username or "<none>"), ("***" if pw else "<none>"), do_publish, topic)

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        try:
            client.enable_logger(self._logger.getChild("paho"))
        except Exception:
            pass
        if username:
            client.username_pw_set(username, pw)

        result = {"success": False, "error": None, "rc": None, "rtt_ms": None}
        connected_evt = threading.Event()
        published_evt = threading.Event()
        mid_holder = {"mid": None}

        def on_connect(c, u, flags, rc, properties=None):
            result["rc"] = rc
            if rc == 0:
                self._logger.info("[TEST] MQTT CONNECT OK (rc=0)")
                if do_publish:
                    payload = json.dumps({"plugin": "factor_mqtt", "status": "ok", "ts": time.time()})
                    info = c.publish(topic, payload, qos=1, retain=False)  # ✅ QoS 1 → PUBACK 확인
                    mid_holder["mid"] = info.mid
            else:
                self._logger.error("[TEST] MQTT CONNECT FAIL rc=%s", rc)
                result["error"] = f"연결 실패 (코드: {rc})"
            connected_evt.set()  # ✅ 콜백에서는 신호만

        def on_publish(c, u, mid, properties=None):
            if mid_holder["mid"] == mid:
                self._logger.info("[TEST] MQTT PUBLISH OK topic=%s", topic)
                published_evt.set()

        def on_disconnect(c, u, rc, properties=None):
            self._logger.info("[TEST] MQTT DISCONNECT rc=%s", rc)

        client.on_connect = on_connect
        client.on_publish = on_publish
        client.on_disconnect = on_disconnect

        t0 = time.time()
        try:
            self._logger.info("[TEST] MQTT connect() 시도...")
            client.connect(host, port, 10)
            client.loop_start()

            # ✅ 메인 쓰레드에서 '연결' 완료 대기
            if not connected_evt.wait(6):
                result["error"] = "연결 시간 초과"
            elif result["rc"] == 0 and do_publish:
                # ✅ 메인 쓰레드에서 '발행 완료(PUBACK)' 대기
                if not published_evt.wait(3):
                    self._logger.warning("[TEST] MQTT PUBLISH TIMEOUT topic=%s", topic)
                else:
                    result["success"] = True
            else:
                # 연결만 확인하고 발행은 안 한 경우
                result["success"] = (result["rc"] == 0)

        except Exception as e:
            result["error"] = str(e)
            self._logger.exception("[TEST] 예외 발생")
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            client.loop_stop()

        result["rtt_ms"] = int((time.time() - t0) * 1000)
        if result["success"]:
            self._logger.info("[TEST] MQTT 연결 테스트 성공 rtt=%sms", result["rtt_ms"])
            # (선택) 메인 클라이언트가 붙어 있다면 스냅샷 한 번 퍼블리시
            try:
                if self.is_connected and self.mqtt_client:
                    self._publish_message(f"{self._settings.get(['topic_prefix']) or 'octoprint'}/status",
                                        json.dumps(self._make_snapshot()))
                    self._logger.info("[TEST] 스냅샷 전송 완료")
            except Exception as e:
                self._logger.warning("[TEST] 스냅샷 전송 실패: %s", e)
            return {"success": True, "message": "연결 테스트 성공", "rtt_ms": result["rtt_ms"]}
        else:
            err = result["error"] or "연결 시간 초과"
            self._logger.error("[TEST] MQTT 연결 테스트 실패: %s", err)
            return {"success": False, "error": err, "rc": result["rc"], "rtt_ms": result["rtt_ms"]}


    

    def get_update_information(self):
        return {
            "factor_mqtt": {
                "displayName": "MQTT-Plugin from FACTOR",
                "displayVersion": __plugin_version__,
                "type": "github_release",
                "user": "kangbyounggwan",
                "repo": "octoprint-factor-plugin",
                "current": __plugin_version__,
                "pip": "https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/{target_version}.zip",
            }
        }
    
    def _make_snapshot(self):
        """프린터 상태 스냅샷을 생성합니다."""
        import time, json
        
        data  = self._printer.get_current_data() or {}
        temps = self._printer.get_current_temperatures() or {}
        conn  = self._printer.get_current_connection() or {}

        progress = (data.get("progress") or {})
        job      = (data.get("job") or {})
        fileinfo = (job.get("file") or {})
        filament = (job.get("filament") or {})
        flags    = (data.get("state") or {}).get("flags", {})

        size    = fileinfo.get("size") or 0
        filepos = progress.get("filepos") or 0
        file_pct = round((filepos/size*100.0), 2) if size else None

        snapshot = {
            "ts":        time.time(),
            "state": {
                "text": (data.get("state") or {}).get("text"),
                "flags": {
                    "operational": bool(flags.get("operational")),
                    "printing":    bool(flags.get("printing")),
                    "paused":      bool(flags.get("paused")),
                    "error":       bool(flags.get("error")),
                    "ready":       bool(flags.get("ready")),
                }
            },
            "progress": {
                "completion": progress.get("completion"),      # %
                "filepos":    filepos,                         # bytes
                "file_size":  size,                            # bytes
                "file_pct":   file_pct,                        # %
                "print_time": progress.get("printTime"),       # sec
                "time_left":  progress.get("printTimeLeft"),   # sec
                "time_left_origin": progress.get("printTimeLeftOrigin"),
            },
            "job": {
                "file": {
                    "name":   fileinfo.get("name"),
                    "origin": fileinfo.get("origin"),   # local/sdcard
                    "date":   fileinfo.get("date"),
                },
                "estimated_time": job.get("estimatedPrintTime"),
                "last_time":      job.get("lastPrintTime"),
                "filament":       filament,            # tool0.length/volume 등 그대로 유지
            },
            "axes": {
                "currentZ": data.get("currentZ")
            },
            "temperatures": temps,                      # tool0/bed/chamber: actual/target/offset
            "connection": conn,                         # port/baudrate/printerProfile/state
            "sd": (data.get("sd") or {}),
        }
        return snapshot

    @octoprint.plugin.BlueprintPlugin.route("/snapshot", methods=["GET"])
    def get_snapshot(self):
        """REST API로 스냅샷을 반환합니다."""
        return self._make_snapshot()

    def _start_snapshot_timer(self):
        """스냅샷 전송 타이머를 시작합니다."""
        if self._snapshot_timer:  # 중복 방지
            return
        interval = float(self._settings.get(["periodic_interval"]) or 1.0)
        self._snapshot_timer = RepeatedTimer(interval, self._snapshot_tick, run_first=True)
        self._snapshot_timer.start()
        self._logger.info(f"[FACTOR MQTT] snapshot timer started every {interval}s")

    def _stop_snapshot_timer(self):
        """스냅샷 전송 타이머를 중지합니다."""
        if self._snapshot_timer:
            self._snapshot_timer.cancel()
            self._snapshot_timer = None
            self._logger.info("[FACTOR MQTT] snapshot timer stopped")

    def _snapshot_tick(self):
        """스냅샷 타이머 콜백 함수"""
        # 연결되어 있지 않으면 아무것도 안 함 (MQTT 재연결을 기다림)
        if not (self.is_connected and self.mqtt_client):
            return
        # 스냅샷 만들어 퍼블리시 (이미 만들었던 함수 재사용)
        try:
            payload = self._make_snapshot()
            topic = f"{self._settings.get(['topic_prefix']) or 'octoprint'}/status"
            self._publish_message(topic, json.dumps(payload))
        except Exception as e:
            self._logger.debug(f"snapshot tick error: {e}")


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MqttPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config":
            __plugin_implementation__.get_update_information
    }