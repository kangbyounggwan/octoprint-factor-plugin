/* globals OctoPrint, ko, $, API_BASEURL */
$(function () {
    function MqttViewModel(parameters) {
      var self = this;
    // [AUTH ADD] 설정: 실제 서버 주소로 교체하세요
    var AUTH_URL = "plugin/factor_mqtt/auth/login";

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
        .not("#factor-mqtt-auth-overlay *, #factor-mqtt-register-overlay *")
        .prop("disabled", !!disabled);
      $("#settings_dialog .modal-footer .btn-primary").prop("disabled", !!disabled);
    }

    // [AUTH ADD] 로그인 오버레이 렌더
    self.renderLoginOverlay = function () {
      var root = $("#settings_plugin_factor_mqtt");
      if (!root.length) return;
      if (!root.css("position") || root.css("position") === "static") {
        root.css("position", "relative");
      }
      if (!$("#factor-mqtt-auth-overlay").length) {
        var overlay = $(
          '<div id="factor-mqtt-auth-overlay" style="position:absolute; inset:0; background:rgba(255,255,255,0.92); z-index:10; display:flex; align-items:center; justify-content:center;">' +
            '<div style="width:100%; max-width:380px; background:#fff; border:1px solid #ddd; border-radius:8px; padding:16px; box-shadow:0 2px 8px rgba(0,0,0,0.1);">' +
              '<div style="font-weight:bold; font-size:14px; margin-bottom:10px;">로그인 후 MQTT 설정을 사용할 수 있습니다</div>' +
              '<div style="display:flex; flex-direction:column; gap:8px;">' +
                '<input type="text" id="fm-login-id" class="form-control" placeholder="Email">' +
                '<input type="password" id="fm-login-pw" class="form-control" placeholder="PW">' +
                '<button id="fm-login-btn" class="btn btn-primary btn-sm">로그인</button>' +
                '<div id="fm-login-status" style="color:#666; min-height:18px;"></div>' +
              '</div>' +
            '</div>' +
          '</div>'
        );
        root.prepend(overlay);

        $("#fm-login-btn").on("click", function () {
          var email = ($("#fm-login-id").val() || "").trim();
          var pw = $("#fm-login-pw").val() || "";
          if (!email || !pw) {
            $("#fm-login-status").text("Email과 PW를 입력하세요.");
            return;
          }
          $("#fm-login-status").text("로그인 중...");

          fetch(AUTH_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email, password: pw })
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              var ok = !!(data && (data.success === true || (!data.error && (data.user || data.session))));
              if (ok) {
                sessionStorage.setItem("factor_mqtt.auth", JSON.stringify(data));
                self.authResp(data);
                self.isAuthed(true);
                // 로그인 완료 → 2단계로 전환
                self.wizardStep(2);
                self.renderRegisterOverlay();
                self.updateAuthBarrier();
              } else {
                var msg = (data && data.error && data.error.message) ? data.error.message : "인증 실패";
                $("#fm-login-status").text(msg);
                self.isAuthed(false);
              }
            })
            .catch(function (e) {
              $("#fm-login-status").text("통신 오류: " + e);
              self.isAuthed(false);
            });
        });
      }
    };

    // [AUTH ADD] 오버레이 토글 + 가드 적용
    self.updateAuthBarrier = function () {
      var authed = !!self.isAuthed();
      // 로그인 오버레이는 미인증시에만 노출
      $("#factor-mqtt-auth-overlay").toggle(!authed);
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

    self.renderRegisterOverlay = function () {
      var root = $("#settings_plugin_factor_mqtt");
      if (!root.length) return;
      if (!root.css("position") || root.css("position") === "static") root.css("position", "relative");
      if (!$("#factor-mqtt-register-overlay").length) {
        var html =
          '<div id="factor-mqtt-register-overlay" style="position:absolute; inset:0; background:rgba(255,255,255,0.92); z-index:9; display:flex; align-items:center; justify-content:center;">' +
            '<div style="width:100%; max-width:420px; background:#fff; border:1px solid #ddd; border-radius:8px; padding:16px; box-shadow:0 2px 8px rgba(0,0,0,0.1);">' +
              '<div style="font-weight:bold; font-size:14px; margin-bottom:10px;">2단계: 프린터 등록</div>' +
              '<div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">' +
                '<input type="text" id="fm-instance-id" class="form-control" placeholder="Instance ID (UUID)" style="flex:1; min-width:240px;">' +
                '<button id="fm-instance-gen" class="btn btn-default btn-sm">생성</button>' +
                '<button id="fm-register-btn" class="btn btn-primary btn-sm">등록</button>' +
              '</div>' +
              '<div id="fm-register-status" style="margin-top:8px; color:#666; min-height:18px;"></div>' +
            '</div>' +
          '</div>';
        root.prepend($(html));

        if (!self.instanceId()) self.instanceId(genUuid());
        $("#fm-instance-id").val(self.instanceId());

        $("#fm-instance-gen").on("click", function () {
          var iid = genUuid(); self.instanceId(iid); $("#fm-instance-id").val(iid);
        });

        $("#fm-register-btn").on("click", function () {
          var iid = ($("#fm-instance-id").val() || "").trim();
          if (!iid) { $("#fm-register-status").text("Instance ID를 입력/생성하세요."); return; }
          $("#fm-register-status").text("등록 중...");

          var auth = self.authResp() || {}; var user = auth.user || null;
          fetch("plugin/factor_mqtt/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ instance_id: iid, user: user })
          })
          .then(function (r) { return r.json().then(function (j){ return {ok:r.ok, status:r.status, data:j}; }); })
          .then(function (res) {
            if (res.ok || (res.data && res.data.success === true)) {
              $("#fm-register-status").text("등록 성공");
              sessionStorage.setItem("factor_mqtt.instanceId", iid);
              self.wizardStep(3);
              $("#factor-mqtt-register-overlay").remove();
              self.updateAuthBarrier();
            } else {
              var msg = (res.data && (res.data.error || res.data.message)) || ("등록 실패 (" + res.status + ")");
              $("#fm-register-status").text(msg);
            }
          })
          .catch(function (e) { $("#fm-register-status").text("통신 오류: " + e); });
        });
      }
      $("#factor-mqtt-register-overlay").toggle(self.wizardStep() === 2);
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
  
      self.connectionStatus = ko.observable("연결 확인 중...");
      self.isConnected = ko.observable(false);
      self.onBeforeBinding = function () {
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
  
        // [WIZARD] 초기 단계 결정
        self.renderLoginOverlay();
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
              self.renderRegisterOverlay();
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
              if (!registered) self.renderRegisterOverlay();
            }
            self.updateAuthBarrier();
            self.checkConnectionStatus();
          });
      };
  
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
  