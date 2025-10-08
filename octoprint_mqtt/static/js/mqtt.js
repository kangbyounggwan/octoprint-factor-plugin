/* globals OctoPrint, ko, $, API_BASEURL */
$(function () {
    function MqttViewModel(parameters) {
      var self = this;
    // [AUTH ADD] 설정: 실제 서버 주소로 교체하세요
    var AUTH_URL = "plugin/factor_mqtt/auth/login";

    // 최종 API 호출 URL 계산 유틸 (API_BASEURL 적용)
    function buildApiUrl(path) {
      try {
        // 블루프린트 경로(/plugin/...)는 /api 프리픽스를 붙이지 않음
        if (path.indexOf("/plugin/") === 0 || path.indexOf("plugin/") === 0) {
          return (path.charAt(0) === "/") ? path : ("/" + path);
        }
        var base = (typeof API_BASEURL !== "undefined" && API_BASEURL) ? API_BASEURL : "/api/";
        if (base.charAt(base.length - 1) !== "/") base += "/";
        path = (path.charAt(0) === "/" ? path.substring(1) : path);
        return base + path;
      } catch (e) {
        if (path.indexOf("/plugin/") === 0 || path.indexOf("plugin/") === 0) {
          return (path.charAt(0) === "/") ? path : ("/" + path);
        }
        return "/api/" + (path.charAt(0) === "/" ? path.substring(1) : path);
      }
    }

    // [AUTH ADD] 상태 저장
    self.isAuthed = ko.observable(!!sessionStorage.getItem("factor_mqtt.auth"));
    self.authResp = ko.observable(self.isAuthed() ? JSON.parse(sessionStorage.getItem("factor_mqtt.auth")) : null);
    // [WIZARD] 단계 및 인스턴스ID
    self.wizardStep = ko.observable(1); // 1: 로그인, 2: 등록, 3: MQTT 설정
    self.instanceId = ko.observable(sessionStorage.getItem("factor_mqtt.instanceId") || "");

    // [AUTH ADD] 공용 가드: 입력/저장 비활성화
    function setInputsDisabled(disabled) {
      var root = $("#settings_plugin_factor_mqtt");
      if (!root.length) return;
      root.find("input, select, textarea, button")
        .not("#factor-mqtt-auth-overlay *, #factor-mqtt-register-overlay *, #tab-login *, #tab-register *")
        .prop("disabled", !!disabled);
      $("#settings_dialog .modal-footer .btn-primary").prop("disabled", !!disabled);
    }

    // [WIZARD] 로그인 탭 이벤트 바인딩
    self.bindLoginTab = function () {
      // 중복 바인딩 방지
      if ($("#fm-login-btn").data("bound")) return;
      $("#fm-login-btn").data("bound", true);
      $("#fm-login-btn").on("click", function () {
        var email = ($("#fm-login-id").val() || "").trim();
        var pw = $("#fm-login-pw").val() || "";
        if (!email || !pw) { $("#fm-login-status").text("Email과 PW를 입력하세요."); return; }
        $("#fm-login-status").text("로그인 중...");
        // 최종 호출 URL 로깅(경로 문제 즉시 확인)
        var reqUrl = buildApiUrl(AUTH_URL);
        var maskedEmail = email.replace(/.(?=.*@)/g, "*");
        try { console.info("[FACTOR][LOGIN][REQ]", { url: reqUrl, email: maskedEmail }); } catch (e) {}

        // OctoPrint.postJson: 자동으로 /api 프리픽스(/api/plugin/...)와 헤더 포함
        OctoPrint.postJson(AUTH_URL, { email: email, password: pw })
          .done(function (data, textStatus, jqXHR) {
            try {
              console.info("[FACTOR][LOGIN][OK]", {
                status: jqXHR && jqXHR.status,
                url: (jqXHR && jqXHR.responseURL) || reqUrl,
                keys: data ? Object.keys(data) : []
              });
            } catch (e) {}
            var ok = !!(data && (data.success === true || (!data.error && (data.user || data.session))));
            if (ok) {
              sessionStorage.setItem("factor_mqtt.auth", JSON.stringify(data));
              self.authResp(data); self.isAuthed(true);
              self.wizardStep(2);
              self.renderRegisterTab();
              self.updateAuthBarrier();
            } else {
              var msg = (data && data.error && data.error.message) ? data.error.message : "인증 실패";
              $("#fm-login-status").text(msg); self.isAuthed(false);
            }
          })
          .fail(function (xhr) {
            var msg = (xhr && xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.message)) || "로그인 실패";
            if (xhr && xhr.status === 404) {
              msg = "엔드포인트(경로) 404: " + ((xhr && xhr.responseURL) || reqUrl) + " - API 프리픽스(/api) 확인 필요";
            }
            try {
              console.error("[FACTOR][LOGIN][FAIL]", {
                status: xhr && xhr.status,
                statusText: xhr && xhr.statusText,
                url: (xhr && xhr.responseURL) || reqUrl,
                respJSON: xhr && xhr.responseJSON,
                respText: xhr && xhr.responseText && xhr.responseText.slice(0, 512)
              });
            } catch (e) {}
            $("#fm-login-status").text(msg); self.isAuthed(false);
          });
      });
    };

    // [AUTH ADD] 오버레이 토글 + 가드 적용
    self.updateAuthBarrier = function () {
      var authed = !!self.isAuthed();
      // 3단계에서만 전체 활성화
      setInputsDisabled(!(authed && self.wizardStep() === 3));
      if (authed && self.wizardStep() === 3) {
        try { self.checkConnectionStatus(); } catch (e) {}
      }
    };

    // [WIZARD] 2단계: 등록 오버레이
    function genUuid() {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c){ var r=Math.random()*16|0, v=c==='x'?r:(r&0x3|0x8); return v.toString(16); });
    }

    self.renderRegisterTab = function () {
      var root = $("#settings_plugin_factor_mqtt");
      if (!root.length) return;
      // 바인딩(중복 방지)
      if (!self.instanceId()) self.instanceId(genUuid());
      $("#fm-instance-id").val(self.instanceId());
      if (!$("#fm-register-btn").data("bound")) {
        $("#fm-register-btn").data("bound", true);
        // 토큰 선택 셀렉트 채우기: 현재는 로그인 토큰 1개만 존재하므로, "신규 등록"과 "로그인 토큰 사용" 두 옵션 제공
        var auth = self.authResp() || {}; var token = auth.access_token || auth.accessToken;
        var sel = $("#fm-register-select");
        sel.empty();
        sel.append('<option value="__new__">신규 등록</option>');
        // 기존 등록된 UUID 조회(API)
        // 기존 UUID 목록은 서버 프록시로 안전하게 호출
        if (token) {
          OctoPrint.ajax("GET", "plugin/factor_mqtt/summary", { headers: { "Authorization": "Bearer " + token } })
            .done(function (resp) {
              try {
                var list = (resp && resp.items) || resp || [];
                list.forEach(function (it) {
                  var id = it.device_uuid || it.uuid || it.instance_id || it.id;
                  var name = it.model || it.name || it.label || "Unknown";
                  if (!id) return; // UUID 없으면 제외
                  sel.append('<option value="' + id + '">' + name + ' (' + id + ')</option>');
                });
              } catch (e) {}
            });
        }

        // 셀렉트 변경 시 UI 토글
        sel.on("change", function () {
          var v = $(this).val();
          var isNew = (v === "__new__");
          $("#fm-instance-id, #fm-instance-gen, #fm-register-btn").toggle(isNew);
          $("#fm-register-next").toggle(!isNew);
          if (!isNew && v && v !== "__token__") {
            // 기존 UUID 선택 시 그 값을 instanceId로 세팅
            self.instanceId(v); $("#fm-instance-id").val(v);
          }
        }).trigger("change");

        $("#fm-register-next").on("click", function () {
          // 기존 등록 선택 시 바로 3단계로 이동
          var v = sel.val();
          if (v && v !== "__new__") {
            if (v !== "__token__") self.instanceId(v);
            // 서버에 저장 요청
            try {
              OctoPrint.postJson("plugin/factor_mqtt/device", { device_uuid: self.instanceId() });
            } catch (e) {}
            self.wizardStep(3); self.updateAuthBarrier();
          }
        });
        // 상태 패널 채우기: 서버 status에서 요약 읽기
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status").done(function (r) {
          try {
            var ps = (r && r.printer_summary) || {};
            var c = ps.connection || {}; var prof = (c.profile || {});
            var size = ps.size || {};
            var lines = [];
            var iid = r && r.instance_id;
            if (iid) lines.push("Instance ID: " + iid);
            if (c.state) lines.push("상태: " + c.state);
            if (c.port) lines.push("포트: " + c.port);
            if (c.baudrate) lines.push("속도: " + c.baudrate);
            if (prof.name) lines.push("프로필: " + prof.name);
            if (prof.model) lines.push("모델: " + prof.model);
            if (size.width || size.depth || size.height) {
              lines.push("사이즈: " + [size.width, size.depth, size.height].filter(Boolean).join(" x "));
            }
            var html = lines.map(function (t){ return '<div class="text-info">' + t + '</div>'; }).join("");
            $("#fm-register-conn").html(html || '<div class="text-muted">프린터 연결 정보가 없습니다.</div>');
          } catch (e) {}
        });
        $("#fm-instance-gen").on("click", function () {
          var iid = genUuid(); self.instanceId(iid); $("#fm-instance-id").val(iid);
        });
        $("#fm-register-btn").on("click", function () {
          var iid = ($("#fm-instance-id").val() || "").trim();
          if (!iid) { $("#fm-register-status").text("Instance ID를 입력/생성하세요."); return; }
          $("#fm-register-status").text("등록 중...");
          var auth = self.authResp() || {}; var user = auth.user || null; var token = auth.access_token || auth.accessToken;
          var body = { instance_id: iid, user: user && { id: user.id } };
          if (token) body.access_token = token;
          OctoPrint.postJson("plugin/factor_mqtt/register", body)
            .done(function (data) {
              if (data && (data.success === true || data.raw || Object.keys(data).length)) {
                $("#fm-register-status").text("등록 성공"); sessionStorage.setItem("factor_mqtt.instanceId", iid);
                // 서버에 저장 요청
                try {
                  OctoPrint.postJson("plugin/factor_mqtt/device", { device_uuid: iid });
                } catch (e) {}
                self.wizardStep(3); self.updateAuthBarrier();
              } else {
                $("#fm-register-status").text("등록 실패");
              }
            })
            .fail(function (xhr) {
              var msg = (xhr && xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.message)) || ("등록 실패 (" + (xhr && xhr.status) + ")");
              $("#fm-register-status").text(msg);
            });
        });
      }
    };
  
      self.settingsViewModel = parameters[0];
      self.loginState = parameters[1];
  
      // 화면용 observable들
      self.brokerHost = ko.observable();
      self.brokerPort = ko.observable();
      self.brokerUsername = ko.observable();
      self.brokerPassword = ko.observable();
      self.topicPrefix = ko.observable();
      self.qosLevel = ko.observable();
      self.retainMessages = ko.observable(false);
      self.publishStatus = ko.observable(false);
      self.publishProgress = ko.observable(false);
       self.publishTemperature = ko.observable(false);
       self.publishGcode = ko.observable(false);
       self.publishSnapshot = ko.observable(false);
       self.periodicInterval = ko.observable(1.0);
      // 카메라 URL
      self.cameraStreamUrl = ko.observable("");
  
      self.connectionStatus = ko.observable("연결 확인 중...");
      self.isConnected = ko.observable(false);

      // 로그인/마법사 초기화 유틸 (모달 열릴 때마다 1. 로그인으로 강제)
      function resetWizardToLogin() {
        try { sessionStorage.removeItem("factor_mqtt.auth"); } catch (e) {}
        self.isAuthed(false);
        self.authResp(null);
        self.wizardStep(1);
        self.updateAuthBarrier();
        self.bindLoginTab();
      }
      self.onBeforeBinding = function () {
        // 모달 재오픈 시 항상 1. 로그인 탭으로 이동
        resetWizardToLogin();
        var s = self.settingsViewModel && self.settingsViewModel.settings;
        if (!s || !s.plugins || !s.plugins.factor_mqtt) {   // ✅ 여기
          console.warn("factor_mqtt settings not ready");
          return;
        }
        self.pluginSettings = s.plugins.factor_mqtt;        // ✅ 여기
  
        // KO observable 읽기 (JS에서는 () 호출)
        self.brokerHost(self.pluginSettings.broker_host());
        self.brokerPort(self.pluginSettings.broker_port());
        self.brokerUsername(self.pluginSettings.broker_username());
        self.brokerPassword(self.pluginSettings.broker_password());
        self.topicPrefix(self.pluginSettings.topic_prefix());
        self.qosLevel(String(self.pluginSettings.qos_level()));
        self.retainMessages(!!self.pluginSettings.retain_messages());
        self.publishStatus(!!self.pluginSettings.publish_status());
        self.publishProgress(!!self.pluginSettings.publish_progress());
         self.publishTemperature(!!self.pluginSettings.publish_temperature());
         self.publishGcode(!!self.pluginSettings.publish_gcode());
         self.publishSnapshot(!!self.pluginSettings.publish_snapshot());
         self.periodicInterval(parseFloat(self.pluginSettings.periodic_interval()) || 1.0);
        // 카메라 URL (observable/문자열 모두 처리)
        try {
          var cam = self.pluginSettings.camera;
          if (cam) {
            var val = (typeof cam.stream_url === "function") ? cam.stream_url() : (cam.stream_url || "");
            self.cameraStreamUrl(val || "");
          }
        } catch (e) {}
  
        // [WIZARD] 탭 클릭: 뒤로는 허용, 앞으로는 금지
        $("#settings_plugin_factor_mqtt .nav-tabs a[data-step]").off("click").on("click", function (e) {
          e.preventDefault();
          var target = parseInt($(this).attr("data-step"), 10) || 1;
          var cur = self.wizardStep();
          if (target <= cur) {
            self.wizardStep(target);
            self.updateAuthBarrier();
            if (target === 2) { self.renderRegisterTab(); setTimeout(bindCameraSection, 0); }
          }
        });

        // [WIZARD] 초기 단계 결정 (강제 로그인 탭 유지)
        self.bindLoginTab();
        var authed = !!self.isAuthed();
        // 서버 상태에서 registered/instance_id 참고
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status")
          .done(function (r) {
            var registered = !!(r && r.registered);
            var iid = (r && r.instance_id) || sessionStorage.getItem("factor_mqtt.instanceId") || "";
            if (iid) { self.instanceId(iid); }
            if (!authed) {
              self.wizardStep(1);
              self.updateAuthBarrier();
            } else if (!registered) {
              self.wizardStep(2);
              self.renderRegisterTab();
              setTimeout(bindCameraSection, 0);
              self.updateAuthBarrier();
            } else {
              self.wizardStep(3);
              self.updateAuthBarrier();
            }
            self.checkConnectionStatus();
          })
          .fail(function () {
            if (!authed) {
              self.wizardStep(1);
            } else {
              // 상태 실패 시 등록여부를 로컬 기준으로 추정
              var registered = !!sessionStorage.getItem("factor_mqtt.instanceId");
              self.wizardStep(registered ? 3 : 2);
              if (!registered) { self.renderRegisterOverlay(); setTimeout(bindCameraSection, 0); }
            }
            self.updateAuthBarrier();
            self.checkConnectionStatus();
          });

        // settings 모달이 열릴 때마다 로그인 탭으로 리셋
        try {
          $(document).off("shown shown.bs.modal", "#settings_dialog").on("shown shown.bs.modal", "#settings_dialog", function(){
            if ($("#settings_plugin_factor_mqtt").is(":visible")) {
              resetWizardToLogin();
            }
          });
        } catch (e) {}
      };

      // --- 카메라 UI 바인딩 (등록 탭) ---
      function bindCameraSection() {
        var $url = $("#fm-camera-url");
        if (!$url.length) return;
        if (!$url.data("inited")) {
          $url.data("inited", true);
          $url.val(self.cameraStreamUrl() || "");
          $("#fm-camera-test").on("click", function(){
            var url = ($url.val() || "").trim();
            if (!url) { $("#fm-camera-status").text("URL을 입력하세요."); return; }
            self.cameraStreamUrl(url);
            var $modal = $("#cameraStreamModal");
            // settings 모달 내부라 중첩 모달 z-index 문제가 있을 수 있어 body로 이동
            try { if (!$modal.parent().is("body")) { $modal.appendTo("body"); } } catch(e) {}
            if (!$modal.data("bound")) {
              $modal.data("bound", true);
              // 명시적으로 닫기 동작 바인딩 (부트스트랩 2/3 호환)
              $modal.on("click", ".close, [data-dismiss='modal']", function(ev){
                ev.preventDefault();
                try { $modal.modal("hide"); } catch(e) { $modal.hide(); }
                return false;
              });
              // 숨김 시 미리보기 해제
              $modal.on("hidden hidden.bs.modal", function(){
                $("#cameraStreamPreview").attr("src", "");
              });
            }
            $("#cameraStreamPreview").attr("src", url);
            $modal.modal({show:true, backdrop:true, keyboard:true});
          });
          $("#fm-camera-save").on("click", function(){
            var url = ($url.val() || "").trim();
            self.cameraStreamUrl(url);
            $("#fm-camera-status").text("저장 중...");
            OctoPrint.postJson("plugin/factor_mqtt/camera", { stream_url: url })
              .done(function(){
                $("#fm-camera-status").text("저장 완료");
                try {
                  var cam = self.pluginSettings && self.pluginSettings.camera;
                  if (cam) {
                    if (typeof cam.stream_url === "function") cam.stream_url(url); else cam.stream_url = url;
                  }
                } catch (e) {}
                // 서버 등록 API에 반영 (토큰/instance_id 자동 전송)
                try {
                  var auth = self.authResp() || {}; var token = auth.access_token || auth.accessToken;
                  var iid = self.instanceId() || (self.pluginSettings && self.pluginSettings.instance_id && self.pluginSettings.instance_id());
                  var body = { instance_id: iid };
                  if (token) body.access_token = token;
                  OctoPrint.postJson("plugin/factor_mqtt/register", body);
                } catch (e) {}
              })
              .fail(function(xhr){
                var msg = (xhr && xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.message)) || ("HTTP " + (xhr && xhr.status));
                $("#fm-camera-status").text("저장 실패: " + msg);
              });
          });
        }
      }
  
      // Settings 저장 직전에 파이썬 설정(observable)으로 되돌려 넣기
      var _orig_onSettingsBeforeSave = self.onSettingsBeforeSave;
      self.onSettingsBeforeSave = function () {
        if (self.wizardStep() !== 3) {
          alert("3단계(등록 완료) 이후에 저장할 수 있습니다.");
          return;
        }
        if (!self.isAuthed()) {
          alert("로그인 후 저장할 수 있습니다.");
          self.updateAuthBarrier();
          return;
        }
        if (typeof _orig_onSettingsBeforeSave === "function") {
          _orig_onSettingsBeforeSave();
          return;
        }
        if (!self.pluginSettings) return;
  
        self.pluginSettings.broker_host(self.brokerHost());
        self.pluginSettings.broker_port(parseInt(self.brokerPort() || 1883, 10));
        self.pluginSettings.broker_username(self.brokerUsername());
        self.pluginSettings.broker_password(self.brokerPassword());
        self.pluginSettings.topic_prefix(self.topicPrefix());
        self.pluginSettings.qos_level(parseInt(self.qosLevel() || 1, 10));
        self.pluginSettings.retain_messages(!!self.retainMessages());
        self.pluginSettings.publish_status(!!self.publishStatus());
        self.pluginSettings.publish_progress(!!self.publishProgress());
         self.pluginSettings.publish_temperature(!!self.publishTemperature());
         self.pluginSettings.publish_gcode(!!self.publishGcode());
         self.pluginSettings.publish_snapshot(!!self.publishSnapshot());
         self.pluginSettings.periodic_interval(parseFloat(self.periodicInterval()) || 1.0);
        // 카메라 값도 메모리 설정에 반영
        try {
          if (self.pluginSettings.camera) {
            if (typeof self.pluginSettings.camera.stream_url === "function") self.pluginSettings.camera.stream_url(self.cameraStreamUrl());
            else self.pluginSettings.camera.stream_url = self.cameraStreamUrl();
          }
        } catch (e) {}
  
        // 저장 후 플러그인에서 _connect_mqtt 재시도하므로 조금 기다렸다 상태 재확인
        setTimeout(self.checkConnectionStatus, 1000);
      };
  
      // 상태 확인 (GET)
      var _orig_checkConnectionStatus = self.checkConnectionStatus;
      self.checkConnectionStatus = function () {
        if (self.wizardStep() !== 3) {
          self.connectionStatus("등록 완료 후 확인할 수 있습니다.");
          self.isConnected(false);
          return;
        }
        if (!self.isAuthed()) {
          self.connectionStatus("로그인이 필요합니다.");
          self.isConnected(false);
          return;
        }
        if (typeof _orig_checkConnectionStatus === "function") {
          _orig_checkConnectionStatus();
          return;
        }
        if (!self.loginState.isUser()) {
          self.connectionStatus("로그인이 필요합니다.");
          self.isConnected(false);
          return;
        }
        // OctoPrint.ajax: 세션/CSRF 자동 처리
        OctoPrint.ajax("GET", "plugin/factor_mqtt/status")
          .done(function (r) {
            if (r && r.connected) {
              self.connectionStatus("MQTT 브로커에 연결됨");
              self.isConnected(true);
            } else {
              self.connectionStatus("MQTT 브로커에 연결되지 않음");
              self.isConnected(false);
            }
          })
          .fail(function () {
            self.connectionStatus("연결 상태를 확인할 수 없습니다.");
            self.isConnected(false);
          });
      };
  
      // 연결 테스트 (POST)
      self.testConnection = function () {
        self.connectionStatus("연결 테스트 중...");
  
        var payload = {
          broker_host: self.brokerHost(),
          broker_port: parseInt(self.brokerPort() || 0, 10),
          broker_username: self.brokerUsername(),
          broker_password: self.brokerPassword(),
          publish: true,
          // 서버 쪽에서 topic_prefix 키를 쓰므로 test_topic 지정 안 해도 되지만,
          // 명시적으로 넣고 싶다면 아래처럼:
          test_topic: (self.topicPrefix() || "octoprint") + "/test"
        };
  
        // OctoPrint.postJson: CSRF/세션/헤더 자동
        OctoPrint.postJson("plugin/factor_mqtt/test", payload)
          .done(function (r) {
            if (r && r.success) {
              self.connectionStatus("연결 테스트 성공!");
              self.isConnected(true);
            } else {
              self.connectionStatus("연결 테스트 실패: " + (r && r.error ? r.error : "알 수 없는 오류"));
              self.isConnected(false);
            }
          })
          .fail(function (xhr) {
            var err = "연결 테스트 중 오류 발생";
            try {
              if (xhr && xhr.responseJSON && xhr.responseJSON.error) {
                err += ": " + xhr.responseJSON.error;
              }
            } catch (e) {}
            self.connectionStatus(err);
            self.isConnected(false);
          });
      };
    }
  
    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel", "loginStateViewModel"],
      elements: ["#settings_plugin_factor_mqtt"] // settings 템플릿의 root 요소 id와 일치해야 함
    });
  });
  