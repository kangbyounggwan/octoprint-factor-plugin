from pathlib import Path
from setuptools import setup

README = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="octoprint-factor-plugin",
    version="2.5.6",
    description="FACTOR Plugin - Remote monitoring and camera integration for OctoPrint",
    long_description=README,
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
        "paho-mqtt>=2.0.0",
    ],
    python_requires=">=3.8,<4",

    entry_points={
        "octoprint.plugin": [
            "factor_mqtt = octoprint_mqtt",
        ]
    },
)
