#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup

__plugin_name__ = "MQTT-Plugin from FACTOR"
__plugin_pythoncompat__ = ">=3.7,<4"

setup(
    name="octoprint-mqtt",
    version="1.0.0",
    description="MQTT-Plugin from FACTOR - MQTT integration plugin for OctoPrint",
    long_description=__doc__,
    long_description_content_type="text/markdown",
    author="FACTOR",
    author_email="tlvh109@gmail.com",
    url="https://github.com/kangbyounggwan/octoprint-factor-plugin",   
    license="AGPLv3",
    packages=["octoprint_mqtt"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "OctoPrint>=1.4.0",
        "paho-mqtt>=1.5.0"
    ],
    entry_points={
        "octoprint.plugin": [
            "mqtt = octoprint_mqtt"
        ]
    },
    python_requires=">=3.7,<4"
)
