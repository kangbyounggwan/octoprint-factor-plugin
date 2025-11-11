/* globals OctoPrint */
/**
 * Simple i18n helper for FACTOR MQTT plugin
 */
(function() {
    "use strict";

    var translations = {};
    var currentLang = "ko"; // default

    // Load translations
    function loadTranslations(lang, callback) {
        // OctoPrint plugin asset URL format
        var url = "plugin/factor_mqtt/static/translations/" + lang + ".json?" + Date.now();
        $.ajax({
            url: url,
            dataType: "json",
            cache: false,
            success: function(data) {
                translations[lang] = data;
                if (callback) callback();
            },
            error: function() {
                console.warn("Failed to load translations for " + lang);
                if (callback) callback();
            }
        });
    }

    // Get translated text
    function t(key) {
        var keys = key.split(".");
        var obj = translations[currentLang];

        for (var i = 0; i < keys.length; i++) {
            if (obj && obj.hasOwnProperty(keys[i])) {
                obj = obj[keys[i]];
            } else {
                // Fallback to Korean if key not found
                obj = translations["ko"];
                for (var j = 0; j < keys.length; j++) {
                    if (obj && obj.hasOwnProperty(keys[j])) {
                        obj = obj[keys[j]];
                    } else {
                        return key; // Return key if not found
                    }
                }
                break;
            }
        }

        return typeof obj === "string" ? obj : key;
    }

    // Detect browser language
    function detectLanguage() {
        var lang = navigator.language || navigator.userLanguage;
        if (lang) {
            lang = lang.toLowerCase();
            if (lang.startsWith("ko")) {
                return "ko";
            } else if (lang.startsWith("en")) {
                return "en";
            }
        }
        return "ko"; // default
    }

    // Initialize
    function init(callback) {
        currentLang = detectLanguage();

        // Load both languages
        var loaded = 0;
        var complete = function() {
            loaded++;
            if (loaded >= 2 && callback) {
                callback();
            }
        };

        loadTranslations("ko", complete);
        loadTranslations("en", complete);
    }

    // Export
    window.FactorMQTT_i18n = {
        init: init,
        t: t,
        setLanguage: function(lang) {
            if (lang === "ko" || lang === "en") {
                currentLang = lang;
            }
        },
        getCurrentLanguage: function() {
            return currentLang;
        }
    };
})();
