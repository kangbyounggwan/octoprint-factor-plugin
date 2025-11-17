import octoprint.plugin
from octoprint.filemanager.destinations import FileDestinations
from octoprint.filemanager.util import DiskFileWrapper
import tempfile
import os
import base64
import re


def _validate_filename(filename: str) -> bool:
    """Validate filename to prevent path traversal and injection."""
    if not filename:
        return False
    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    # Allow only alphanumeric, underscore, hyphen, and dot
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
        return False
    # Must end with .gcode or .g
    if not (filename.lower().endswith('.gcode') or filename.lower().endswith('.g')):
        return False
    # Reasonable length limit
    if len(filename) > 255:
        return False
    return True


def _validate_gcode_content(content: bytes, max_size_mb: int = 100) -> tuple:
    """
    Validate G-code content for safety.
    Returns (is_valid, error_message).
    """
    # Check size
    if len(content) > max_size_mb * 1024 * 1024:
        return False, f"File too large (max {max_size_mb}MB)"

    # Check for dangerous patterns (optional, commented out for flexibility)
    # dangerous_patterns = [b'M997', b'M999']  # Firmware reset commands
    # for pattern in dangerous_patterns:
    #     if pattern in content:
    #         return False, f"Dangerous command detected: {pattern.decode()}"

    return True, None


def handle_gcode_message(self, data: dict):
    """MQTT로 받은 G-code 메시지 처리"""
    action = (data.get("action") or "").lower()
    job_id = data.get("job_id")
    now = __import__("time").time()
    
    if not job_id:
        self._logger.warning("[FACTOR MQTT] job_id 누락")
        return

    # 업로드된 파일 즉시 프린트 (업로드 화이트리스트 기반)
    if action == "print":
        try:
            name = (data.get("filename") or "").strip()
            origin = (data.get("origin") or "local").lower()  # local | sd | sdcard
            if not name:
                self._logger.warning("[FACTOR MQTT] print filename 누락")
                return

            # Validate filename
            if not _validate_filename(name):
                self._logger.error(f"[FACTOR MQTT] 유효하지 않은 파일명: {name}")
                return

            is_sd = origin in ("sd", "sdcard", "sd_card")
            if is_sd:
                wl = getattr(self, "_uploaded_sd_files", set())
            else:
                wl = getattr(self, "_uploaded_local_files", set())
            if wl and name not in wl:
                self._logger.warning(f"[FACTOR MQTT] 허용되지 않은 파일 print 요청: {name}")
                return
            self._printer.select_file(name, sd=is_sd, printAfterSelect=True)
            self._logger.info(f"[FACTOR MQTT] print 시작: origin={'sd' if is_sd else 'local'} name={name}")
        except Exception as e:
            self._logger.error(f"[FACTOR MQTT] print 실패: {e}")
        return

    if action == "start":
        # 시작 로직
        filename = data.get("filename") or f"{job_id}.gcode"
        total = int(data.get("total_chunks") or 0)
        upload_target = (data.get("upload_traget") or data.get("upload_target") or "").lower()

        # Validate filename
        if not _validate_filename(filename):
            self._logger.error(f"[FACTOR MQTT] 유효하지 않은 파일명: {filename}")
            return

        # Validate chunk count
        if total <= 0 or total > 10000:  # Reasonable limit
            self._logger.warning(f"[FACTOR MQTT] total_chunks 범위 초과: {total}")
            return

        self._gcode_jobs[job_id] = {
            "filename": filename,
            "total": total,
            "chunks": {},
            "created_ts": now,
            "last_ts": now,
            "upload_target": upload_target
        }
        self._logger.info(f"[FACTOR MQTT] GCODE 수신 시작 job={job_id} file={filename} total={total}")
        return

    state = self._gcode_jobs.get(job_id)
    if not state:
        self._logger.warning(f"[FACTOR MQTT] 알 수 없는 job_id={job_id}")
        return

    state["last_ts"] = now

    if action == "chunk":
        # 청크 처리 로직
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
        # 청크 조합 및 업로드
        total = state["total"]
        got = len(state["chunks"])
        if got != total:
            self._logger.warning(f"[FACTOR MQTT] end 수신 but chunk 불일치 {got}/{total}")
            return

        ordered = [state["chunks"][i] for i in range(total)]
        content = b"".join(ordered)

        # Validate G-code content
        is_valid, error_msg = _validate_gcode_content(content)
        if not is_valid:
            self._logger.error(f"[FACTOR MQTT] G-code 검증 실패: {error_msg}")
            self._gcode_jobs.pop(job_id, None)
            return

        filename = state["filename"]
        target = (data.get("target") or state.get("upload_target") or "").lower()
        if target not in ("sd", "local", "local_print"):
            target = (self._settings.get(["receive_target_default"]) or "local").lower()

        # 청크 데이터 정리
        self._gcode_jobs.pop(job_id, None)

        # 업로드 처리 (당신의 로직 재사용)
        upload_result = _upload_gcode_content(self, content, filename, target)

        if upload_result.get("success"):
            self._logger.info(f"[FACTOR MQTT] 업로드 성공 job={job_id} file={filename} target={target}")
        else:
            self._logger.error(f"[FACTOR MQTT] 업로드 실패 job={job_id}: {upload_result.get('error')}")
        return

def _upload_gcode_content(self, content: bytes, filename: str, target: str):
    """청크 데이터를 target에 따라 업로드"""
    try:
        if target == "sd":
            return _upload_bytes_to_sd(self, content, filename)
        elif target in ("local", "local_print"):
            res = _upload_bytes_to_local(self, content, filename)
            # local_print 는 저장 후 즉시 인쇄
            if target == "local_print" and res.get("success"):
                try:
                    # path가 아닌 파일명으로 select_file 호출 (LOCAL 루트)
                    self._printer.select_file(filename, False, printAfterSelect=True)
                except Exception:
                    pass
            return res
        else:
            return {"success": False, "error": f"알 수 없는 target: {target}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _upload_bytes_to_local(self, content: bytes, filename: str):
    """바이트 데이터를 로컬에 업로드"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.gcode') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        file_object = DiskFileWrapper(filename, tmp_path)
        username = None
        try:
            user = getattr(self, "_user_manager", None)
            if user:
                cu = user.get_current_user()
                if cu:
                    username = cu.get_name()
        except Exception:
            pass

        saved_path = self._file_manager.add_file(
            FileDestinations.LOCAL,
            filename,
            file_object,
            allow_overwrite=True,
            user=username
        )

        try:
            if not hasattr(self, "_uploaded_local_files"):
                self._uploaded_local_files = set()
            self._uploaded_local_files.add(filename)
        except Exception:
            pass

        return {
            "success": True,
            "path": saved_path,
            "message": f"파일이 로컬에 저장되었습니다: {saved_path}"
        }

    except Exception as e:
        return {"success": False, "error": f"로컬 업로드 실패: {str(e)}"}
    finally:
        # 항상 임시 파일 정리
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

def _upload_bytes_to_sd(self, content: bytes, filename: str):
    """바이트 데이터를 SD카드에 업로드"""
    tmp_path = None
    try:
        if not getattr(self._printer, "is_sd_ready", lambda: False)():
            return {"success": False, "error": "SD카드가 준비되지 않았습니다"}

        if self._printer.is_printing():
            return {"success": False, "error": "프린트 중에는 SD카드 업로드가 불가능합니다"}

        # 임시 로컬 파일로 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix='.gcode') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        file_object = DiskFileWrapper(filename, tmp_path)
        username = None
        try:
            user = getattr(self, "_user_manager", None)
            if user:
                cu = user.get_current_user()
                if cu:
                    username = cu.get_name()
        except Exception:
            pass

        # 임시 로컬 파일로 저장
        temp_filename = f"temp_{filename}"
        local_path = self._file_manager.add_file(
            FileDestinations.LOCAL,
            temp_filename,
            file_object,
            allow_overwrite=True,
            user=username
        )

        def on_success(local, remote, elapsed=None, *args, **kwargs):
            try:
                self._logger.info(f"SD카드 업로드 성공:remote={remote}, local={local}")
                # 임시 로컬 파일 삭제

                try:
                    self._printer.refresh_sd_files()
                except Exception:
                    pass
                try:
                    self._file_manager.remove_file(FileDestinations.LOCAL, temp_filename)
                except:
                    pass
            except Exception:
                pass

        def on_failure(local, remote, elapsed=None, *args, **kwargs):
            try:
                self._logger.error(f"SD카드 업로드 실패: remote={remote}, local={local}")
                # 임시 로컬 파일 삭제
                try:
                    self._file_manager.remove_file(FileDestinations.LOCAL, temp_filename)
                except:
                    pass
            except Exception:
                pass

        remote_filename = self._printer.add_sd_file(
            filename,
            self._file_manager.path_on_disk(FileDestinations.LOCAL, temp_filename),
            on_success=on_success,
            on_failure=on_failure,
            tags={"source:plugin", "mqtt:upload"}
        )

        try:
            if not hasattr(self, "_uploaded_sd_files"):
                self._uploaded_sd_files = set()
            # SD는 원격 파일명(프린터가 가진 경로/이름)이 기준일 수 있음. 우선 요청 filename으로 관리
            self._uploaded_sd_files.add(filename)
        except Exception:
            pass

        return {
            "success": True,
            "remote_filename": remote_filename,
            "message": f"파일이 SD카드에 업로드되었습니다: {remote_filename}"
        }

    except Exception as e:
        return {"success": False, "error": f"SD카드 업로드 실패: {str(e)}"}
    finally:
        # 항상 임시 파일 정리
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass