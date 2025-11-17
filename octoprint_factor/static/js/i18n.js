/* globals OctoPrint */
/**
 * Simple i18n helper for FACTOR MQTT plugin
 */
(function() {
    "use strict";

    var translations = {};
    var currentLang = "en"; // default to English

    // Load translations
    function loadTranslations(lang, callback) {
        // OctoPrint plugin asset URL format
        var url = "plugin/octoprint_factor/static/translations/" + lang + ".json?" + Date.now();
        $.ajax({
            url: url,
            dataType: "json",
            cache: false,
            success: function(data) {
                translations[lang] = data;
                console.log("Loaded translations for " + lang + ":", data);
                if (callback) callback();
            },
            error: function(xhr, status, error) {
                console.error("Failed to load translations for " + lang + ":", status, error, "URL:", url);
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
                // Fallback to English if key not found
                obj = translations["en"];
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
        return "en"; // default to English
    }

    // Initialize
    function init(callback) {
        // Check if user has saved language preference
        var savedLang = localStorage.getItem("factor_mqtt_lang");
        if (savedLang && (savedLang === "ko" || savedLang === "en")) {
            currentLang = savedLang;
        } else {
            // Auto-detect from browser, but default to English
            currentLang = detectLanguage();
        }

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

    // Apply translations to DOM
    function applyTranslations() {
        // Translate all elements with data-i18n attribute
        $("[data-i18n]").each(function() {
            var $el = $(this);
            var key = $el.attr("data-i18n");
            var translated = t(key);

            // Check if the translated text contains HTML
            if (translated.indexOf('<') !== -1) {
                $el.html(translated);
            } else {
                $el.text(translated);
            }
        });

        // Translate placeholders
        $("[data-i18n-placeholder]").each(function() {
            var $el = $(this);
            var key = $el.attr("data-i18n-placeholder");
            $el.attr("placeholder", t(key));
        });

        // Translate HTML content
        $("[data-i18n-html]").each(function() {
            var $el = $(this);
            var key = $el.attr("data-i18n-html");
            $el.html(t(key));
        });
    }

    // Export
    window.FactorMQTT_i18n = {
        init: init,
        t: t,
        setLanguage: function(lang) {
            if (lang === "ko" || lang === "en") {
                currentLang = lang;
                // Save preference
                localStorage.setItem("factor_mqtt_lang", lang);
                // Re-apply translations
                applyTranslations();
            }
        },
        getCurrentLanguage: function() {
            return currentLang;
        },
        applyTranslations: applyTranslations
    };
})();
