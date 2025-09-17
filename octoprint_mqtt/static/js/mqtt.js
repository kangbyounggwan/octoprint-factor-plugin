$(function() {
    function MqttViewModel(parameters) {
        var self = this;
        
        self.settings = parameters[0];
        self.loginState = parameters[1];
        
        self.connectionStatus = ko.observable("연결 확인 중...");
        self.isConnected = ko.observable(false);
        
        // 설정 값들을 observable로 바인딩
        self.brokerHost = ko.observable();
        self.brokerPort = ko.observable();
        self.brokerUsername = ko.observable();
        self.brokerPassword = ko.observable();
        self.topicPrefix = ko.observable();
        self.qosLevel = ko.observable();
        self.retainMessages = ko.observable();
        self.publishStatus = ko.observable();
        self.publishProgress = ko.observable();
        self.publishTemperature = ko.observable();
        self.publishGcode = ko.observable();
        
        // 설정 로드
        self.onBeforeBinding = function() {
            self.settings = self.settings.settings;
            
            self.brokerHost(self.settings.broker_host());
            self.brokerPort(self.settings.broker_port());
            self.brokerUsername(self.settings.broker_username());
            self.brokerPassword(self.settings.broker_password());
            self.topicPrefix(self.settings.broker_topic_prefix());
            self.qosLevel(self.settings.qos_level());
            self.retainMessages(self.settings.retain_messages());
            self.publishStatus(self.settings.publish_status());
            self.publishProgress(self.settings.publish_progress());
            self.publishTemperature(self.settings.publish_temperature());
            self.publishGcode(self.settings.publish_gcode());
            
            // 연결 상태 확인
            self.checkConnectionStatus();
        };
        
        // 연결 상태 확인
        self.checkConnectionStatus = function() {
            if (!self.loginState.isUser()) {
                self.connectionStatus("로그인이 필요합니다.");
                self.isConnected(false);
                return;
            }
            
            $.ajax({
                url: API_BASEURL + "plugin/mqtt/status",
                type: "GET",
                dataType: "json",
                success: function(response) {
                    if (response.connected) {
                        self.connectionStatus("MQTT 브로커에 연결됨");
                        self.isConnected(true);
                    } else {
                        self.connectionStatus("MQTT 브로커에 연결되지 않음");
                        self.isConnected(false);
                    }
                },
                error: function() {
                    self.connectionStatus("연결 상태를 확인할 수 없습니다.");
                    self.isConnected(false);
                }
            });
        };
        
        // 연결 테스트
        self.testConnection = function() {
            self.connectionStatus("연결 테스트 중...");
            
            $.ajax({
                url: API_BASEURL + "plugin/mqtt/test",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    broker_host: self.brokerHost(),
                    broker_port: self.brokerPort(),
                    broker_username: self.brokerUsername(),
                    broker_password: self.brokerPassword()
                }),
                contentType: "application/json",
                success: function(response) {
                    if (response.success) {
                        self.connectionStatus("연결 테스트 성공!");
                        self.isConnected(true);
                    } else {
                        self.connectionStatus("연결 테스트 실패: " + response.error);
                        self.isConnected(false);
                    }
                },
                error: function(xhr) {
                    var error = "연결 테스트 중 오류 발생";
                    if (xhr.responseJSON && xhr.responseJSON.error) {
                        error += ": " + xhr.responseJSON.error;
                    }
                    self.connectionStatus(error);
                    self.isConnected(false);
                }
            });
        };
        
        // 설정 저장 후 연결 상태 업데이트
        self.onSettingsBeforeSave = function() {
            // 설정이 저장된 후 연결 상태를 다시 확인
            setTimeout(function() {
                self.checkConnectionStatus();
            }, 1000);
        };
    }
    
    // 뷰모델 등록
    OCTOPRINT_VIEWMODELS.push({
        construct: MqttViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel"],
        elements: ["#settings_plugin_mqtt"]
    });
});