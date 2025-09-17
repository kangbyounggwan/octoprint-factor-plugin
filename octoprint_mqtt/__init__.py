# -*- coding: utf-8 -*-

import octoprint.plugin

class MqttPlugin(octoprint.plugin.SettingsPlugin,
                 octoprint.plugin.AssetPlugin,
                 octoprint.plugin.TemplatePlugin,
                 octoprint.plugin.StartupPlugin,
                 octoprint.plugin.ShutdownPlugin,
                 octoprint.plugin.EventHandlerPlugin,
                 octoprint.plugin.BlueprintPlugin,
                 octoprint.plugin.SoftwareUpdatePlugin):
    
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
            broker_topic_prefix="octoprint",
            qos_level=1,
            retain_messages=True,
            publish_status=True,
            publish_progress=True,
            publish_temperature=True,
            publish_gcode=True
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
    
    def get_template_configs(self):
        return [
            dict(type="settings", template="mqtt_settings.jinja2", custom_bindings=False)
        ]
    
    ##~~ StartupPlugin mixin
    
    def on_startup(self, host, port):
        self._connect_mqtt()
    
    ##~~ ShutdownPlugin mixin
    
    def on_shutdown(self):
        self._disconnect_mqtt()
    
    ##~~ EventHandlerPlugin mixin
    
    def on_event(self, event, payload):
        if not self.is_connected:
            return
        
        topic_prefix = self._settings.get(["broker_topic_prefix"])
        
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
            
            self.mqtt_client = mqtt.Client()
            
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
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            self._logger.info("MQTT 브로커에 성공적으로 연결되었습니다.")
        else:
            self.is_connected = False
            self._logger.error(f"MQTT 연결 실패. 코드: {rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        self.is_connected = False
        self._logger.info("MQTT 브로커와의 연결이 끊어졌습니다.")
    
    def _on_mqtt_publish(self, client, userdata, mid):
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
        """MQTT 연결을 테스트합니다."""
        try:
            import json
            import paho.mqtt.client as mqtt
            
            data = request.get_json(force=True, silent=True) or {}
            
            # 테스트용 클라이언트 생성
            test_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
            
            # 인증 정보 설정
            if data.get("broker_username"):
                test_client.username_pw_set(data["broker_username"], data.get("broker_password", ""))
            
            # 연결 결과를 저장할 변수
            connection_result = {"success": False, "error": None}
            
            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    connection_result["success"] = True
                    client.disconnect()
                else:
                    connection_result["error"] = f"연결 실패 (코드: {rc})"
            
            def on_disconnect(client, userdata, rc):
                pass
            
            test_client.on_connect = on_connect
            test_client.on_disconnect = on_disconnect
            
            # 연결 시도
            host = data.get("broker_host", "localhost")
            port = int(data.get("broker_port", 1883))
            
            test_client.connect(host, port, 10)
            test_client.loop_start()
            
            # 연결 결과 대기 (최대 5초)
            import time
            timeout = 5
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if connection_result["success"] or connection_result["error"]:
                    break
                time.sleep(0.1)
            
            test_client.loop_stop()
            test_client.disconnect()
            
            if connection_result["success"]:
                return {"success": True, "message": "연결 테스트 성공"}
            else:
                error_msg = connection_result["error"] or "연결 시간 초과"
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    ##~~ SoftwareUpdatePlugin mixin
    
    def get_update_information(self):
        return {
            "mqtt": {
                "displayName": "MQTT-Plugin from FACTOR",
                "displayVersion": self._plugin_version,
                "type": "github_release",
                "user": "kangbyounggwan",
                "repo": "octoprint-factor-plugin",
                "current": self._plugin_version,
                "pip": "https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/{target_version}.zip",
            }
        }

__plugin_name__ = "MQTT-Plugin from FACTOR"
__plugin_pythoncompat__ = ">=3.8,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MqttPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        
    }
