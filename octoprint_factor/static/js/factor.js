/* globals OctoPrint, ko, $, FactorMQTT_i18n */
$(function () {
    // Language selector initialization
    function initLanguageSelector() {
      var currentLang = FactorMQTT_i18n.getCurrentLanguage();

      // Set active state
      $("#fm-lang-selector .btn").removeClass("active");
      $("#fm-lang-selector .btn[data-lang='" + currentLang + "']").addClass("active");

      // Button click event
      $("#fm-lang-selector .btn").off("click").on("click", function() {
        var lang = $(this).attr("data-lang");
        FactorMQTT_i18n.setLanguage(lang);

        // Update UI
        $("#fm-lang-selector .btn").removeClass("active");
        $(this).addClass("active");
      });
    }

    // Connection status management
    var ConnectionStatus = {
      statusColors: {
        ready: { bg: "#d4edda", border: "#c3e6cb", icon: "" },
        pending_registration: { bg: "#fff3cd", border: "#ffeeba", icon: "" },
        not_subscribed: { bg: "#fff3cd", border: "#ffeeba", icon: "" },
        no_instance_id: { bg: "#f8d7da", border: "#f5c6cb", icon: "" },
        disconnected: { bg: "#f8d7da", border: "#f5c6cb", icon: "" },
        error: { bg: "#f8d7da", border: "#f5c6cb", icon: "" }
      },

      updateUI: function(status) {
        var t = FactorMQTT_i18n.t;
        var panel = $("#fm-connection-status");
        var colors = this.statusColors[status.status] || this.statusColors.error;

        // Show panel
        panel.show().css({
          "background-color": colors.bg,
          "border": "1px solid " + colors.border
        });

        // Update icon and text
        $("#fm-status-icon").text(colors.icon);

        // Use i18n for status message
        var statusKey = "status.message." + status.status;
        var statusText = t(statusKey);
        if (statusText === statusKey) {
          statusText = status.message; // Fallback to server message
        }
        $("#fm-status-text").text(statusText);

        // Update details
        $("#fm-mqtt-status").text(status.mqtt_connected ? t("status.connected") : t("status.disconnected"));
        $("#fm-instance-id").text(status.instance_id || t("status.none"));
        $("#fm-subscribed-status").text(status.subscribed ? t("status.yes") : t("status.no"));

        // Show/hide retry button based on status
        if (status.status === "disconnected" || status.status === "not_subscribed") {
          $("#fm-retry-btn").show();
        } else {
          $("#fm-retry-btn").hide();
        }

        // Show details on hover or click
        panel.off("click").on("click", function() {
          $("#fm-status-details").toggle();
        });
      },

      fetch: function() {
        var self = this;
        OctoPrint.ajax("GET", "plugin/octoprint_factor/connection-status")
          .done(function(data) {
            self.updateUI(data);
          })
          .fail(function(xhr) {
            self.updateUI({
              status: "error",
              message: "Failed to fetch status",
              mqtt_connected: false,
              instance_id: null,
              subscribed: false
            });
          });
      },

      retry: function() {
        var self = this;
        $("#fm-retry-btn").prop("disabled", true).find("i").addClass("icon-spin");

        OctoPrint.ajax("POST", "plugin/octoprint_factor/retry-connection")
          .done(function(data) {
            console.log("Retry result:", data);
            // Wait a moment then refresh status
            setTimeout(function() {
              self.fetch();
              $("#fm-retry-btn").prop("disabled", false).find("i").removeClass("icon-spin");
            }, 1500);
          })
          .fail(function(xhr) {
            console.error("Retry failed:", xhr);
            $("#fm-retry-btn").prop("disabled", false).find("i").removeClass("icon-spin");
            self.fetch();
          });
      }
    };

    function MqttViewModel(parameters) {
      var self = this;
      var t = FactorMQTT_i18n.t;

      self.settingsViewModel = parameters[0];

      var setupUrl = "";
      var instanceId = "";
      var statusPollInterval = null;

      // Load setup URL with instance ID
      function loadSetupUrl() {
        OctoPrint.ajax("GET", "plugin/octoprint_factor/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update button href with instance ID
              $("#fm-open-setup").attr("href", setupUrl);

              console.log("Setup URL loaded:", setupUrl);

              // Refresh connection status after getting setup URL
              ConnectionStatus.fetch();
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get setup URL:", xhr);
          });
      }

      // Start polling connection status
      function startStatusPolling() {
        if (statusPollInterval) return;
        statusPollInterval = setInterval(function() {
          ConnectionStatus.fetch();
        }, 10000); // Poll every 10 seconds
      }

      // Stop polling
      function stopStatusPolling() {
        if (statusPollInterval) {
          clearInterval(statusPollInterval);
          statusPollInterval = null;
        }
      }

      self.onBeforeBinding = function () {
        // Initialize i18n and translations
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();
          initLanguageSelector();

          // Load setup URL to get instance ID
          loadSetupUrl();

          // Initial status fetch
          ConnectionStatus.fetch();

          // Bind retry button
          $("#fm-retry-btn").on("click", function(e) {
            e.stopPropagation();
            ConnectionStatus.retry();
          });

          // Bind refresh button
          $("#fm-refresh-btn").on("click", function(e) {
            e.stopPropagation();
            $(this).find("i").addClass("icon-spin");
            ConnectionStatus.fetch();
            setTimeout(function() {
              $("#fm-refresh-btn").find("i").removeClass("icon-spin");
            }, 500);
          });

          // Bind "Open Setup Page" button click
          $("#fm-open-setup").on("click", function() {
            // Call start-setup API to subscribe to MQTT topics
            OctoPrint.ajax("POST", "plugin/octoprint_factor/start-setup")
              .done(function() {
                console.log("Started setup - subscribed to registration topic");
                // Refresh status after starting setup
                setTimeout(function() {
                  ConnectionStatus.fetch();
                }, 1000);
              })
              .fail(function(xhr) {
                console.error("Failed to start setup:", xhr);
              });
            // Continue with opening the URL (don't prevent default)
          });
        });
      };

      // Start polling when settings tab is shown
      self.onSettingsShown = function() {
        ConnectionStatus.fetch();
        startStatusPolling();
      };

      // Stop polling when settings tab is hidden
      self.onSettingsHidden = function() {
        stopStatusPolling();
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttViewModel,
      dependencies: ["settingsViewModel"],
      elements: ["#settings_plugin_factor_mqtt"]
    });

    // Wizard ViewModel
    function MqttWizardViewModel(parameters) {
      var self = this;
      var t = FactorMQTT_i18n.t;

      var setupUrl = "";
      var instanceId = "";

      // Load setup URL with instance ID for wizard
      function loadWizardSetupUrl() {
        OctoPrint.ajax("GET", "plugin/octoprint_factor/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update wizard button href with instance ID
              $("#wizard-open-setup").attr("href", setupUrl);

              console.log("Wizard setup URL loaded:", setupUrl);
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get wizard setup URL:", xhr);
          });
      }

      self.onBeforeWizardTabChange = function(next, current) {
        return true;
      };

      self.onBeforeWizardFinish = function() {
        return true;
      };

      self.onWizardFinish = function() {
        // Mark as configured (optional)
      };

      self.onAfterBinding = function() {
        // Initialize i18n for wizard
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();

          // Initialize language selector for wizard
          var currentLang = FactorMQTT_i18n.getCurrentLanguage();
          $("#wizard-lang-selector .btn").removeClass("active");
          $("#wizard-lang-selector .btn[data-lang='" + currentLang + "']").addClass("active");

          $("#wizard-lang-selector .btn").on("click", function() {
            var lang = $(this).attr("data-lang");
            FactorMQTT_i18n.setLanguage(lang);
            $("#wizard-lang-selector .btn").removeClass("active");
            $(this).addClass("active");
          });

          // Load setup URL to get instance ID
          loadWizardSetupUrl();
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttWizardViewModel,
      elements: ["#wizard_plugin_factor_mqtt"]
    });
});
