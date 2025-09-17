# -*- coding: utf-8 -*-
import json
from flask import request  # Blueprint에서 사용
import octoprint.plugin



__plugin_name__ = "MQTT-Plugin from FACTOR"
__plugin_pythoncompat__ = ">=3.8,<4"
__plugin_version__ = "1.0.4"
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
        )
    
    def get_settings_version(self):
        return 1
    
    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._disconnect_mqtt()
        self._connect_mqtt()
    
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
        # 필요시 추가 로그
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
            
            # 연결
            host = self._settings.get(["broker_host"])
            port = self._settings.get(["broker_port"])
            self.mqtt_client.connect(host, port, 60)
            self.mqtt_client.loop_start()
            
            self._logger.info(f"MQTT 클라이언트가 {host}:{port}에 연결을 시도합니다.")
            
        except Exception as e:
            self._logger.error(f"MQTT 연결 실패: {e}")
    
    def _disconnect_mqtt(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            self.mqtt_client = None
            self.is_connected = False
            self._logger.info("MQTT 클라이언트 연결이 종료되었습니다.")
    
    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.is_connected = True
            self._logger.info("MQTT 브로커에 성공적으로 연결되었습니다.")
        else:
            self.is_connected = False
            self._logger.error(f"MQTT 연결 실패. 코드: {rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc, properties=None):
        self.is_connected = False
        self._logger.info("MQTT 브로커와의 연결이 끊어졌습니다.")
    
    def _on_mqtt_publish(self, client, userdata, mid, properties=None):
        self._logger.debug(f"MQTT 메시지 발행 완료. 메시지 ID: {mid}")
    
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
        """MQTT 연결을 테스트하고 로그를 남깁니다."""
        import time, json
        import paho.mqtt.client as mqtt

        data = request.get_json(force=True, silent=True) or {}
        host = data.get("broker_host", "localhost")
        port = int(data.get("broker_port", 1883))
        username = data.get("broker_username")
        pw_provided = bool(data.get("broker_password"))
        do_publish = bool(data.get("publish", False))
        topic = data.get("test_topic") or f"{self._settings.get(['topic_prefix'])}/test"

        # --- 시작 로그 (민감정보 마스킹) ---
        self._logger.info(
            "[TEST] MQTT 연결 테스트 시작 host=%s port=%s user=%s pw=%s publish=%s topic=%s",
            host, port, (username or "<none>"), ("***" if pw_provided else "<none>"),
            do_publish, topic
        )

        # 테스트 클라이언트 생성 + paho 내부 로그 연결(선택)
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        try:
            client.enable_logger(self._logger.getChild("paho"))  # paho 내부 로그도 OctoPrint 로그로
        except Exception:
            pass

        if username:
            client.username_pw_set(username, data.get("broker_password", ""))

        result = {"success": False, "error": None, "rc": None, "rtt_ms": None}
        t0 = time.time()

        def on_connect(c, u, flags, rc, properties=None):
            result["rc"] = rc
            if rc == 0:
                self._logger.info("[TEST] MQTT CONNECT OK (rc=0)")
                if do_publish:
                    payload = json.dumps({"plugin": "factor_mqtt", "status": "ok", "ts": time.time()})
                    info = c.publish(topic, payload, qos=0, retain=False)
                    info.wait_for_publish(timeout=3)
                    if info.is_published():
                        self._logger.info("[TEST] MQTT PUBLISH OK topic=%s", topic)
                    else:
                        self._logger.warning("[TEST] MQTT PUBLISH TIMEOUT topic=%s", topic)
                result["success"] = True
            else:
                self._logger.error("[TEST] MQTT CONNECT FAIL rc=%s", rc)
                result["error"] = f"연결 실패 (코드: {rc})"
            c.disconnect()

        def on_disconnect(c, u, rc, properties=None, reason_code=None):
            self._logger.info("[TEST] MQTT DISCONNECT rc=%s", rc)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect

        try:
            self._logger.info("[TEST] MQTT connect() 시도...")
            client.connect(host, port, 10)
            client.loop_start()

            # 최대 6초 대기
            timeout = 6
            while time.time() - t0 < timeout and not (result["success"] or result["error"]):
                time.sleep(0.1)
        except Exception as e:
            result["error"] = str(e)
            self._logger.exception("[TEST] 예외 발생")
        finally:
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass

        result["rtt_ms"] = int((time.time() - t0) * 1000)

        if result["success"]:
            self._logger.info("[TEST] MQTT 연결 테스트 성공 rtt=%sms", result["rtt_ms"])
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


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MqttPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config":
            __plugin_implementation__.get_update_information
    }