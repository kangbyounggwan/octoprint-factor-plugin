$(function () {
    function MqttViewModel(parameters) {
      var self = this;
  
      self.settingsViewModel = parameters[0];   // settingsViewModel
      self.loginState = parameters[1];          // loginStateViewModel
  
      // 플러그인 설정(observable 트리)의 정확한 경로
      // NOTE: plugin identifier가 factor_mqtt 라고 가정
      self.pluginSettings = self.settingsViewModel.settings.plugins.factor_mqtt;
  
      // 화면용 observable (폼과 바인딩)
      self.brokerHost        = ko.observable();
      self.brokerPort        = ko.observable();
      self.brokerUsername    = ko.observable();
      self.brokerPassword    = ko.observable();
      self.topicPrefix       = ko.observable();
      self.qosLevel          = ko.observable();
      self.retainMessages    = ko.observable(false);
      self.publishStatus     = ko.observable(false);
      self.publishProgress   = ko.observable(false);
      self.publishTemperature= ko.observable(false);
      self.publishGcode      = ko.observable(false);
  
      self.connectionStatus  = ko.observable("연결 확인 중...");
      self.isConnected       = ko.observable(false);
  
      // 화면 초기 로드 시: pluginSettings의 observable 값들을 폼 observable에 채워 넣기
      self.onBeforeBinding = function () {
        // pluginSettings.* 는 KO observable 이므로 JS에서 읽을 때는 () 로 언랩
        self.brokerHost(        self.pluginSettings.broker_host()        );
        self.brokerPort(        self.pluginSettings.broker_port()        );
        self.brokerUsername(    self.pluginSettings.broker_username()    );
        self.brokerPassword(    self.pluginSettings.broker_password()    );
        self.topicPrefix(       self.pluginSettings.topic_prefix()       ); // <- 키 이름 주의
        self.qosLevel(          String(self.pluginSettings.qos_level())  ); // select value는 문자열로
        self.retainMessages(    !!self.pluginSettings.retain_messages()  );
        self.publishStatus(     !!self.pluginSettings.publish_status()   );
        self.publishProgress(   !!self.pluginSettings.publish_progress() );
        self.publishTemperature(!!self.pluginSettings.publish_temperature());
        self.publishGcode(      !!self.pluginSettings.publish_gcode()    );
  
        self.checkConnectionStatus();
      };
  
      // 저장 직전: 폼 값을 pluginSettings에 되돌려 써서 OctoPrint가 저장하도록
      self.onSettingsBeforeSave = function () {
        self.pluginSettings.broker_host(        self.brokerHost() );
        self.pluginSettings.broker_port(        parseInt(self.brokerPort() || 0, 10) );
        self.pluginSettings.broker_username(    self.brokerUsername() );
        self.pluginSettings.broker_password(    self.brokerPassword() );
        self.pluginSettings.topic_prefix(       self.topicPrefix() );
        self.pluginSettings.qos_level(          parseInt(self.qosLevel() || 0, 10) );
        self.pluginSettings.retain_messages(    !!self.retainMessages() );
        self.pluginSettings.publish_status(     !!self.publishStatus() );
        self.pluginSettings.publish_progress(   !!self.publishProgress() );
        self.pluginSettings.publish_temperature(!!self.publishTemperature() );
        self.pluginSettings.publish_gcode(      !!self.publishGcode() );
  
        // 저장 후 연결상태 재확인(조금 여유)
        setTimeout(self.checkConnectionStatus, 1000);
      };
  
      // 연결 상태 확인
      self.checkConnectionStatus = function () {
        if (!self.loginState.isUser()) {
          self.connectionStatus("로그인이 필요합니다.");
          self.isConnected(false);
          return;
        }
  
        $.ajax({
          url: API_BASEURL + "plugin/mqtt/status",
          type: "GET",
          dataType: "json",
          success: function (response) {
            if (response && response.connected) {
              self.connectionStatus("MQTT 브로커에 연결됨");
              self.isConnected(true);
            } else {
              self.connectionStatus("MQTT 브로커에 연결되지 않음");
              self.isConnected(false);
            }
          },
          error: function () {
            self.connectionStatus("연결 상태를 확인할 수 없습니다.");
            self.isConnected(false);
          }
        });
      };
  
      // 연결 테스트
      self.testConnection = function () {
        self.connectionStatus("연결 테스트 중...");
  
        $.ajax({
          url: API_BASEURL + "plugin/mqtt/test",
          type: "POST",
          dataType: "json",
          data: JSON.stringify({
            broker_host:     self.brokerHost(),
            broker_port:     parseInt(self.brokerPort() || 0, 10),
            broker_username: self.brokerUsername(),
            broker_password: self.brokerPassword()
          }),
          contentType: "application/json",
          success: function (response) {
            if (response && response.success) {
              self.connectionStatus("연결 테스트 성공!");
              self.isConnected(true);
            } else {
              self.connectionStatus("연결 테스트 실패: " + (response && response.error ? response.error : "알 수 없는 오류"));
              self.isConnected(false);
            }
          },
          error: function (xhr) {
            var error = "연결 테스트 중 오류 발생";
            if (xhr.responseJSON && xhr.responseJSON.error) error += ": " + xhr.responseJSON.error;
            self.connectionStatus(error);
            self.isConnected(false);
          }
        });
      };
    }
  
    // 뷰모델 등록: elements 선택자를 실제 HTML id와 일치시킴
    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel", "loginStateViewModel"],
      elements: ["#settings_plugin_factor_mqtt"]   // <<< 여기!
    });
  });
  