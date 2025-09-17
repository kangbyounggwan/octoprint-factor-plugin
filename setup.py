from pathlib import Path
from setuptools import setup, find_packages

README = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="octoprint-factor-mqtt",                 # 고유한 패키지 이름
    version="1.0.0",
    description="MQTT-Plugin from FACTOR - MQTT integration plugin for OctoPrint",
    long_description=README,
    long_description_content_type="text/markdown",
    author="FACTOR",
    author_email="tlvh109@gmail.com",
    url="https://github.com/kangbyounggwan/octoprint-factor-plugin",
    license="AGPLv3",

    packages=find_packages(exclude=("tests", "dev*", "examples")),
    include_package_data=True,                    # MANIFEST.in과 함께 사용
    zip_safe=False,

    install_requires=[
        "OctoPrint>=1.4.0",
        "paho-mqtt>=1.5.0",                       # 2.x 사용 시 콜백 v1 강제 또는 v2 시그니처 적용
    ],
    python_requires=">=3.7,<4",

    entry_points={
        "octoprint.plugin": [
            "factor_mqtt = octoprint_mqtt",       # 고유한 플러그인 식별자
        ]
    },

    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Framework :: OctoPrint",
        "Operating System :: OS Independent",
    ],
)