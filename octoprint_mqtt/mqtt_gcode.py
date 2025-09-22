import octoprint.plugin
from octoprint.filemanager.destinations import FileDestinations
from octoprint.filemanager.util import DiskFileWrapper
import tempfile
import os
import base64


def handle_gcode_message(self, data: dict):
    """MQTT로 받은 G-code 메시지 처리"""
    action = (data.get("action") or "").lower()
    job_id = data.get("job_id")
    now = __import__("time").time()
    
    if not job_id:
        self._logger.warning("[FACTOR MQTT] job_id 누락")
        return

    if action == "start":
        # 시작 로직
        filename = data.get("filename") or f"{job_id}.gcode"
        total = int(data.get("total_chunks") or 0)
        upload_target = (data.get("upload_traget") or data.get("upload_target") or "").lower()
        
        if total <= 0:
            self._logger.warning("[FACTOR MQTT] total_chunks 누락/잘못됨")
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

        filename = state["filename"]
        target = (data.get("target") or state.get("upload_target") or "").lower()
        if target not in ("sd", "local", "local_print"):
            target = (self._settings.get(["receive_target_default"]) or "local").lower()

        # 청크 데이터 정리
        self._gcode_jobs.pop(job_id, None)
        
        # 업로드 처리 (당신의 로직 재사용)
        upload_result = self._upload_gcode_content(content, filename, target)
        
        if upload_result.get("success"):
            self._logger.info(f"[FACTOR MQTT] 업로드 성공 job={job_id} file={filename} target={target}")
        else:
            self._logger.error(f"[FACTOR MQTT] 업로드 실패 job={job_id}: {upload_result.get('error')}")
        return

def _upload_gcode_content(self, content: bytes, filename: str, target: str):
    """청크 데이터를 target에 따라 업로드"""
    try:
        if target == "sd":
            return self._upload_bytes_to_sd(content, filename)
        elif target in ("local", "local_print"):
            res = self._upload_bytes_to_local(content, filename)
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
            os.unlink(tmp_path)
        except Exception:
            pass

        return {
            "success": True,
            "path": saved_path,
            "message": f"파일이 로컬에 저장되었습니다: {saved_path}"
        }

    except Exception as e:
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        return {"success": False, "error": f"로컬 업로드 실패: {str(e)}"}

def _upload_bytes_to_sd(self, content: bytes, filename: str):
    """바이트 데이터를 SD카드에 업로드"""
    try:
        if not getattr(self._printer, "is_sd_ready", lambda: False)():
            return {"success": False, "error": "SD카드가 준비되지 않았습니다"}

        if self._printer.is_printing():
            return {"success": False, "error": "프린트 중에는 SD카드 업로드가 불가능합니다"}

        # 임시 로컬 파일로 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix='.gcode') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        try:
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

            def on_success(remote_filename):
                try:
                    self._logger.info(f"SD카드 업로드 성공: {remote_filename}")
                    # 임시 로컬 파일 삭제
                    try:
                        self._file_manager.remove_file(FileDestinations.LOCAL, temp_filename)
                    except:
                        pass
                except Exception:
                    pass

            def on_failure(remote_filename):
                try:
                    self._logger.error(f"SD카드 업로드 실패: {remote_filename}")
                    # 임시 로컬 파일 삭제
                    try:
                        self._file_manager.remove_file(FileDestinations.LOCAL, temp_filename)
                    except:
                        pass
                except Exception:
                    pass

            remote_filename = self._printer.add_sd_file(
                temp_filename,
                self._file_manager.path_on_disk(FileDestinations.LOCAL, temp_filename),
                on_success=on_success,
                on_failure=on_failure,
                tags={"source:plugin", "mqtt:upload"}
            )

            return {
                "success": True,
                "remote_filename": remote_filename,
                "message": f"파일이 SD카드에 업로드되었습니다: {remote_filename}"
            }

        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        return {"success": False, "error": f"SD카드 업로드 실패: {str(e)}"}