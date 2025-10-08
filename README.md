# MQTT-Plugin from FACTOR


옥토프린터용 MQTT 통합 플러그인입니다. 이 플러그인을 통해 옥토프린터의 상태 정보를 MQTT 브로커로 실시간 전송할 수 있습니다.

## 주요 기능

- **실시간 상태 전송**: 프린터 상태, 인쇄 진행률, 온도 정보를 MQTT로 전송
- **G-code 명령 전송**: 프린터로 전송되는 G-code 명령을 MQTT로 전송
- **유연한 설정**: 브로커 주소, 포트, 인증 정보, 토픽 접두사 등 자유롭게 설정
- **QoS 지원**: MQTT QoS 레벨 설정 (0, 1, 2)
- **메시지 유지**: Retain 플래그 설정으로 마지막 메시지 유지
- **연결 테스트**: 설정 UI에서 MQTT 브로커 연결 테스트 가능

## 설치 방법

### 1. 수동 설치

```bash
# 플러그인 디렉토리로 이동
cd ~/.octoprint/plugins/

# 플러그인 클론
git clone https://github.com/kangbyounggwan/octoprint-factor-plugin.git

# 플러그인 디렉토리로 이동
cd octoprint-factor-plugin/

# 의존성 설치
pip install -r requirements.txt

# 플러그인 설치
pip install .
```

### 2. OctoPrint 플러그인 관리자를 통한 설치

1. OctoPrint 웹 인터페이스에서 설정 > 플러그인 관리자로 이동
2. "플러그인 추가" 버튼 클릭
3. 플러그인 URL 입력: `https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/main.zip`
4. 설치 완료 후 OctoPrint 재시작

## 설정 방법

1. OctoPrint 웹 인터페이스에서 설정 > 플러그인으로 이동
2. "MQTT-Plugin from FACTOR" 설정 페이지 열기
3. MQTT 브로커 정보 입력:
   - **브로커 호스트**: MQTT 브로커 주소 
   - **브로커 포트**: MQTT 브로커 포트 (기본값: 1883)
   - **사용자명/비밀번호**: 인증이 필요한 경우 입력
   - **토픽 접두사**: 모든 토픽에 사용될 접두사 (기본값: octoprint)

4. 발행 설정 구성:
   - **QoS 레벨**: 메시지 전달 품질 보장 레벨
   - **메시지 유지**: 브로커가 마지막 메시지를 유지할지 설정
   - **발행할 이벤트**: 전송할 이벤트 유형 선택

5. "연결 테스트" 버튼으로 설정 확인
6. 설정 저장

## MQTT 토픽 구조

플러그인은 다음과 같은 토픽 구조로 메시지를 전송합니다:

```
{토픽_접두사}/status      # 프린터 상태 변경
{토픽_접두사}/progress    # 인쇄 진행률
{토픽_접두사}/temperature # 온도 정보
{토픽_접두사}/gcode       # G-code 명령
```

### 예시 토픽

```
octoprint/status
octoprint/progress
octoprint/temperature
octoprint/gcode
```

## 메시지 형식

모든 메시지는 JSON 형식으로 전송됩니다.

### 상태 메시지 예시

```json
{
  "state_id": "OPERATIONAL",
  "state_string": "Operational"
}
```

### 진행률 메시지 예시

```json
{
  "completion": 45.2,
  "filepos": 1234567,
  "printTime": 1800,
  "printTimeLeft": 2200
}
```

### 온도 메시지 예시

```json
{
  "tool0": {
    "actual": 210.5,
    "target": 220.0,
    "offset": 0
  },
  "bed": {
    "actual": 60.0,
    "target": 60.0,
    "offset": 0
  }
}
```

## 요구사항

- OctoPrint 1.4.0 이상
- Python 3.7 이상
- paho-mqtt 1.5.0 이상

## 문제 해결

### 연결 문제

1. **브로커 주소 확인**: 올바른 IP 주소나 호스트명을 입력했는지 확인
2. **포트 확인**: 방화벽이나 네트워크 설정에서 포트가 차단되지 않았는지 확인
3. **인증 정보**: 사용자명과 비밀번호가 올바른지 확인
4. **MQTT 브로커 상태**: MQTT 브로커가 실행 중인지 확인

### 메시지 전송 문제

1. **QoS 설정**: 네트워크 환경에 맞는 QoS 레벨 설정
2. **토픽 접두사**: 특수문자나 공백이 없는지 확인
3. **로그 확인**: OctoPrint 로그에서 오류 메시지 확인

## 개발자 정보

- **개발자**: FACTOR
- **이메일**: factor@example.com
- **GitHub**: https://github.com/kangbyounggwan/octoprint-factor-plugin

## 라이선스

이 프로젝트는 AGPLv3 라이선스 하에 배포됩니다.

## 기여하기

1. 이 저장소를 포크합니다
2. 새로운 기능 브랜치를 생성합니다 (`git checkout -b feature/amazing-feature`)
3. 변경사항을 커밋합니다 (`git commit -m 'Add some amazing feature'`)
4. 브랜치에 푸시합니다 (`git push origin feature/amazing-feature`)
5. Pull Request를 생성합니다

## 변경 로그

### v1.0.3
- 초기 릴리스
- 기본 MQTT 통합 기능
- 프린터 상태, 진행률, 온도, G-code 전송
- 설정 UI 및 연결 테스트 기능
