# -*- coding: utf-8 -*-
import json
from flask import request  # Blueprint에서 사용
import octoprint.plugin
from octoprint.util import RepeatedTimer
import base64
import io
import time
import hashlib



__plugin_name__ = "MQTT-Plugin from FACTOR"
__plugin_pythoncompat__ = ">=3.8,<4"
__plugin_version__ = "1.0.9"
__plugin_identifier__ = "factor_mqtt"

        
def _as_code(x):
    try:
        v = getattr(x, "value", None)
        if isinstance(v, int):
            return v
        return int(x)
    except Exception:
        s = (str(x) if x is not None else "").strip().lower()
        if s in ("success", "normal disconnection"):
            return 0
        import re
        m = re.search(r"(\d+)", s)
        return int(m.group(1)) if m else -1




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
        self._gcode_jobs = {}
    
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
            periodic_interval=1.0,
            receive_gcode_enabled=True,
            receive_topic_suffix="gcode_in",
            receive_target_default="local_print",
            receive_timeout_sec=300
            
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
            self.mqtt_client.on_message = self._on_mqtt_message
            
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
        rc_i = _as_code(rc)
        self.is_connected = (rc_i == 0)
        if self.is_connected:
            self._logger.info("MQTT 브로커 연결 OK")
            self._start_snapshot_timer()     # ✅ 여기서 시작
            try:
                topic_prefix = self._settings.get(["topic_prefix"]) or "octoprint"
                suffix = self._settings.get(["receive_topic_suffix"]) or "gcode_in"
                qos = int(self._settings.get(["qos_level"]) or 0)
                topic = f"{topic_prefix}/{suffix}/#"
                self.mqtt_client.subscribe(topic, qos=qos)
                self._logger.info(f"[FACTOR MQTT] subscribe: {topic} (qos={qos})")
            except Exception as e:
                self._logger.warning(f"[FACTOR MQTT] subscribe 실패: {e}")
        else:
            self._logger.error(f"MQTT 연결 실패 rc={rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc, properties=None, *args, **kwargs):
        rc_i = _as_code(rc)
        self.is_connected = False
        self._logger.warning(f"MQTT 연결 끊김 rc={rc}")
        # 타이머는 유지해도 되고 멈춰도 됨. 유지하면 재연결 후 자동 퍼블리시됨.
        # 멈추고 싶다면 아래 주석 해제:
        # self._stop_snapshot_timer()
    
    def _on_mqtt_publish(self, client, userdata, mid, *args, **kwargs):
        # paho 2.0: (mid, properties)
        # paho 2.1+: (mid, reasonCode, properties)
        reasonCode = None
        properties = None
        if len(args) == 1:
            properties = args[0]
        elif len(args) >= 2:
            reasonCode, properties = args[0], args[1]

        if reasonCode is not None:
            try:
                rc_i = _as_code(reasonCode)  # 이미 위에 정의됨
            except Exception:
                rc_i = None
            if rc_i is not None:
                self._logger.debug(f"MQTT publish mid={mid} rc={rc_i}")
            else:
                self._logger.debug(f"MQTT publish mid={mid} rc={reasonCode}")
        else:
            self._logger.debug(f"MQTT publish mid={mid}")
        
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
    
    def _on_mqtt_message(self, client, userdata, msg):
        try:
            if not bool(self._settings.get(["receive_gcode_enabled"])):
                return
            topic = msg.topic or ""
            topic_prefix = self._settings.get(["topic_prefix"]) or "octoprint"
            suffix = self._settings.get(["receive_topic_suffix"]) or "gcode_in"
            if not topic.startswith(f"{topic_prefix}/{suffix}"):
                return
            payload = msg.payload.decode("utf-8", errors="ignore") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload or "")
            data = json.loads(payload or "{}")
            self._handle_gcode_message(data)
        except Exception as e:
            self._logger.exception(f"[FACTOR MQTT] on_message 처리 오류: {e}")

    def _handle_gcode_message(self, data: dict):
        action = (data.get("action") or "").lower()
        job_id = data.get("job_id")
        now = time.time()
        if not job_id:
            self._logger.warning("[FACTOR MQTT] job_id 누락")
            return

        self._gc_expired_jobs(now)

        if action == "start":
            filename = data.get("filename") or f"{job_id}.gcode"
            total = int(data.get("total_chunks") or 0)
            if total <= 0:
                self._logger.warning("[FACTOR MQTT] total_chunks 누락/잘못됨")
                return
            self._gcode_jobs[job_id] = {
                "filename": filename,
                "total": total,
                "chunks": {},
                "created_ts": now,
                "last_ts": now
            }
            self._logger.info(f"[FACTOR MQTT] GCODE 수신 시작 job={job_id} file={filename} total={total}")
            return

        state = self._gcode_jobs.get(job_id)
        if not state:
            self._logger.warning(f"[FACTOR MQTT] 알 수 없는 job_id={job_id}, start 먼저 필요")
            return

        state["last_ts"] = now

        if action == "chunk":
            try:
                seq = int(data.get("seq"))
                b64 = data.get("data_b64") or ""
                if seq < 0 or not b64:
                    raise ValueError("seq/data_b64 invalid")
                chunk = base64.b64decode(b64)
                state["chunks"][seq] = chunk
                if len(state["chunks"]) % 50 == 0 or len(state["chunks"]) == 1:
                    self._logger.info(f"[FACTOR MQTT] chunk 수신 job={job_id} {len(state['chunks'])}/{state['total']}")
            except Exception as e:
                self._logger.warning(f"[FACTOR MQTT] chunk 처리 실패: {e}")
            return

        if action == "cancel":
            self._gcode_jobs.pop(job_id, None)
            self._logger.info(f"[FACTOR MQTT] GCODE 수신 취소 job={job_id}")
            return

        if action == "end":
            total = state["total"]
            got = len(state["chunks"])
            if got != total:
                self._logger.warning(f"[FACTOR MQTT] end 수신 but chunk 불일치 {got}/{total}, 조합 중단")
                return

            ordered = [state["chunks"][i] for i in range(total)]
            content = b"".join(ordered)

            expect_md5 = (data.get("md5") or "").lower()
            if expect_md5:
                calc_md5 = hashlib.md5(content).hexdigest()
                if calc_md5 != expect_md5:
                    self._logger.warning(f"[FACTOR MQTT] MD5 불일치 expect={expect_md5} got={calc_md5}")

            filename = state["filename"]
            target = (data.get("target") or "").lower()
            if target not in ("sd", "local_print"):
                target = (self._settings.get(["receive_target_default"]) or "local_print").lower()

            try:
                if target == "sd":
                    self._finalize_job_to_sd(filename, content)
                    self._logger.info(f"[FACTOR MQTT] SD 저장 완료 file={filename}")
                else:
                    self._finalize_job_to_local_and_print(filename, content)
                    self._logger.info(f"[FACTOR MQTT] 로컬 저장+인쇄 시작 file={filename}")
            except Exception as e:
                self._logger.exception(f"[FACTOR MQTT] 최종 처리 실패: {e}")
                return
            finally:
                self._gcode_jobs.pop(job_id, None)
            return

        self._logger.warning(f"[FACTOR MQTT] 지원되지 않는 action={action}")

    def _finalize_job_to_sd(self, filename: str, content: bytes):
        from octoprint.filemanager.destinations import FileDestinations
        stream = io.BytesIO(content)
        stream.seek(0)
        self._file_manager.add_file(FileDestinations.SDCARD, filename, stream, allow_overwrite=True)

    def _finalize_job_to_local_and_print(self, filename: str, content: bytes):
        from octoprint.filemanager.destinations import FileDestinations
        stream = io.BytesIO(content)
        stream.seek(0)
        self._file_manager.add_file(FileDestinations.LOCAL, filename, stream, allow_overwrite=True)
        self._printer.select_file(filename, False, printAfterSelect=True)

    def _gc_expired_jobs(self, now: float = None):
        try:
            if now is None:
                now = time.time()
            timeout = int(self._settings.get(["receive_timeout_sec"]) or 300)
            expired = []
            for job_id, st in self._gcode_jobs.items():
                if now - (st.get("last_ts") or st.get("created_ts") or now) > timeout:
                    expired.append(job_id)
            for job_id in expired:
                self._gcode_jobs.pop(job_id, None)
            if expired:
                self._logger.warning(f"[FACTOR MQTT] 만료된 job 정리: {expired}")
        except Exception:
            pass
    
    def _list_sd_files(self, max_items: int = 100):
        files = []
        try:
            tree = self._file_manager.list_files(recursive=True) or {}
            sd_root = (tree.get("sdcard") or {})

            def walk(node, base_path=""):
                if not isinstance(node, dict):
                    return
                for key, val in node.items():
                    if isinstance(val, dict) and ("children" in val):
                        name = val.get("name") or key or ""
                        walk(val.get("children") or {}, base_path + (name + "/" if name else ""))
                        continue
                    if isinstance(val, dict):
                        name = val.get("name") or key
                        path = val.get("path") or (base_path + (name or ""))
                        files.append({
                            "name": name,
                            "path": path,
                            "size": val.get("size"),
                            "date": val.get("date"),
                        })

            walk(sd_root)
        except Exception as e:
            self._logger.debug(f"SD 목록 추출 실패: {e}")
        return files[:max_items]
    
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
            "broker_port": self._settings.get(["broker_port"]),
            "sd_files": self._list_sd_files(max_items=100)
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
        mid_ref = {"mid": None}

        # v2: (client, userdata, flags, reasonCode, properties)
        def on_connect(c, u, flags, reasonCode, properties=None):
            result["rc"] = _as_code(reasonCode)
            if result["rc"] == 0:
                self._logger.info("[TEST] MQTT CONNECT OK (rc=%s)", result["rc"])
                if do_publish:
                    payload = json.dumps({"plugin": "factor_mqtt", "status": "ok", "ts": time.time()})
                    info = c.publish(topic, payload, qos=1, retain=False)  # PUBACK 확인용 QoS 1
                    mid_ref["mid"] = info.mid
                    # 콜백 안에서는 wait 금지!
            else:
                self._logger.error("[TEST] MQTT CONNECT FAIL rc=%s", result["rc"])
                result["error"] = f"연결 실패 (코드: {result['rc']})"
            connected_evt.set()

        # paho 2.0: (client, userdata, mid, properties)
        # paho 2.1: (client, userdata, mid, reasonCode, properties)
        def on_publish(c, u, mid, *args, **kwargs):
            reasonCode = None
            properties = None
            if len(args) == 1:
                properties = args[0]
            elif len(args) >= 2:
                reasonCode, properties = args[0], args[1]
            if mid_ref["mid"] == mid:
                if reasonCode is not None:
                    self._logger.info("[TEST] MQTT PUBLISH OK topic=%s rc=%s", topic, _as_code(reasonCode))
                else:
                    self._logger.info("[TEST] MQTT PUBLISH OK topic=%s", topic)
                published_evt.set()

        # v2: (client, userdata, disconnect_flags, reasonCode, properties)
        def on_disconnect(c, u, disconnect_flags, reasonCode, properties=None):
            self._logger.info("[TEST] MQTT DISCONNECT flags=%s rc=%s",
                            str(disconnect_flags), _as_code(reasonCode))

        client.on_connect = on_connect
        client.on_publish = on_publish
        client.on_disconnect = on_disconnect

        t0 = time.time()
        try:
            self._logger.info("[TEST] MQTT connect() 시도...")
            client.connect(host, port, 10)
            client.loop_start()

            # 메인 쓰레드 대기(콜백 안에서는 절대 wait 하지 말기!)
            if not connected_evt.wait(6):
                result["error"] = "연결 시간 초과"
            elif result["rc"] == 0 and do_publish:
                if not published_evt.wait(3):
                    self._logger.warning("[TEST] MQTT PUBLISH TIMEOUT topic=%s", topic)
                else:
                    result["success"] = True
            else:
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
            # (선택) 메인 클라이언트가 붙어있다면 스냅샷 1회 발행
            try:
                if self.is_connected and self.mqtt_client:
                    self._publish_message(f"{self._settings.get(['topic_prefix']) or 'octoprint'}/status",
                                        json.dumps(self._make_snapshot()))
                    self._logger.info("[TEST] 스냅샷 전송 완료")
            except Exception as e:
                self._logger.warning("[TEST] 스냅샷 전송 실패: %s", e)
            return {"success": True, "message": "연결 테스트 성공", "rtt_ms": result["rtt_ms"], "rc": result["rc"]}
        else:
            err = result["error"] or "연결 시간 초과"
            self._logger.error("[TEST] MQTT 연결 테스트 실패: %s", err)
            return {"success": False, "error": err, "rtt_ms": result["rtt_ms"], "rc": result["rc"]}



    

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
            self._gc_expired_jobs()
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