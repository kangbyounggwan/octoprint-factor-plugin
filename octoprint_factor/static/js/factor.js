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

    function MqttViewModel(parameters) {
      var self = this;
      var t = FactorMQTT_i18n.t;

      self.settingsViewModel = parameters[0];

      var setupUrl = "";
      var instanceId = "";

      // Load setup URL
      function loadSetupUrl() {
        $("#fm-url-loading").show();
        $("#fm-url-display").hide();

        // Get setup URL
        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              // Update button href
              $("#fm-open-setup").attr("href", setupUrl);

              // Display URL as text
              $("#fm-setup-url-text").text(setupUrl);
              $("#fm-instance-id-text").text(instanceId);

              $("#fm-url-loading").hide();
              $("#fm-url-display").show();
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get setup URL:", xhr);
            $("#fm-url-loading").html('<i class="icon-warning-sign"></i> <span>Failed to load setup URL</span>');
          });
      }

      self.onBeforeBinding = function () {
        // Initialize i18n and translations
        FactorMQTT_i18n.init(function() {
          FactorMQTT_i18n.applyTranslations();
          initLanguageSelector();

          // Load setup URL
          loadSetupUrl();

          // Bind "Open Setup Page" button click
          $("#fm-open-setup").on("click", function() {
            // Call start-setup API to subscribe to MQTT topics
            OctoPrint.ajax("POST", "plugin/factor_mqtt/start-setup")
              .done(function() {
                console.log("Started setup - subscribed to registration topic");
              })
              .fail(function(xhr) {
                console.error("Failed to start setup:", xhr);
              });
            // Continue with opening the URL (don't prevent default)
          });

          // Bind events - Refresh setup URL with NEW instance ID
          $("#fm-refresh-qr").on("click", function() {
            var $btn = $(this);
            $btn.prop("disabled", true).html('<i class="icon-spinner icon-spin"></i> Refreshing...');

            // Call refresh endpoint to generate NEW instance ID
            OctoPrint.ajax("POST", "plugin/factor_mqtt/refresh-qr")
              .done(function(data) {
                if (data && data.success) {
                  setupUrl = data.setup_url;
                  instanceId = data.instance_id;
                  console.log("New instance ID generated:", instanceId);

                  // Update UI with new values directly
                  $("#fm-open-setup").attr("href", setupUrl);
                  $("#fm-setup-url-text").text(setupUrl);
                  $("#fm-instance-id-text").text(instanceId);
                }
              })
              .fail(function(xhr) {
                console.error("Failed to refresh setup URL:", xhr);
                alert("Failed to refresh setup URL. Please try again.");
              })
              .always(function() {
                $btn.prop("disabled", false).html('<i class="icon-refresh"></i> <span data-i18n="setup.button.refresh">Refresh Setup URL</span>');
                FactorMQTT_i18n.applyTranslations();
              });
          });
        });
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

      // Load QR code for wizard
      function loadWizardQRCode() {
        $("#wizard-qr-loading").show();
        $("#wizard-qr-code").hide();

        OctoPrint.ajax("GET", "plugin/factor_mqtt/setup-url")
          .done(function(data) {
            if (data && data.success) {
              setupUrl = data.setup_url;
              instanceId = data.instance_id;

              $("#wizard-open-setup").attr("href", setupUrl);

              var qrUrl = "plugin/factor_mqtt/qrcode?" + Date.now();
              var $img = $("#wizard-qr-code");

              $img.on("load", function() {
                $("#wizard-qr-loading").hide();
                $img.show();
              }).on("error", function() {
                $("#wizard-qr-loading").html('<i class="icon-warning-sign"></i><br><span>Failed to load QR code</span>');
              });

              $img.attr("src", qrUrl);
            }
          })
          .fail(function(xhr) {
            console.error("Failed to get setup URL:", xhr);
            $("#wizard-qr-loading").html('<i class="icon-warning-sign"></i><br><span>Failed to load setup URL</span>');
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

      // Listen for registration confirmation from plugin (via MQTT)
      self.onDataUpdaterPluginMessage = function(plugin, data) {
        if (plugin !== "factor_mqtt") return;

        if (data.type === "registration_confirmed") {
          console.log("✅ Device registration confirmed via MQTT!");

          // Show success message
          new PNotify({
            title: "Registration Complete!",
            text: "Your FACTOR device has been successfully registered. The wizard will now close.",
            type: "success",
            hide: true,
            delay: 3000
          });

          // Close wizard after a short delay
          setTimeout(function() {
            // Trigger wizard completion
            if ($("#wizard_dialog").is(":visible")) {
              $("#wizard_dialog").modal("hide");
            }
            // Reload page to refresh state
            location.reload();
          }, 3000);
        }

        if (data.type === "registration_failed") {
          console.log("❌ Device registration failed:", data.status, data.error);

          var title = data.status === "timeout" ? "Registration Timeout" : "Registration Failed";
          var message = data.error || "An error occurred during registration.";

          // Show error message
          new PNotify({
            title: title,
            text: message + "<br><br>Please refresh the QR code and try again.",
            type: "error",
            hide: true,
            delay: 5000
          });

          // Reload QR code after delay to get new instance ID
          setTimeout(function() {
            loadWizardQRCode();
          }, 5000);
        }
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

          // Load QR code
          loadWizardQRCode();
        });
      };
    }

    OCTOPRINT_VIEWMODELS.push({
      construct: MqttWizardViewModel,
      elements: ["#wizard_plugin_factor_mqtt"]
    });
});
