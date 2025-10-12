# FACTOR × OctoPrint — 외부 모니터링 & 카메라 연동 (무료 베타)

하루 종일 출력 돌려놓고 집에 오니 **스파게티/익스트루더 꼬임**…  
그래서 **OctoPrint와 연동되는 외부 모니터링 플랫폼 ‘FACTOR’**를 만들었습니다.  
**서버 비용 부담 오기 전까지 무료(약 300명 예상)** 로 공개합니다. 피드백 주시면 저녁에 빠르게 반영할게요 🙌

[![status](https://img.shields.io/badge/status-beta-blue)]()
[![platform](https://img.shields.io/badge/OctoPrint-plugin-green)]()
[![license](https://img.shields.io/badge/license-MIT-lightgrey)]()

> 사이트: **https://factor.io.kr**  
> 플러그인(zip): `https://github.com/kangbyounggwan/octoprint-factor-plugin/archive/main.zip`

---

## ✨ 핵심 기능

- **실시간 모니터링**: 출력 진행/상태를 대시보드에서 확인
- **카메라 연동**: 기존 스트림 URL(MJPEG/WebRTC/RTSP/HLS) 그대로 사용
- **간단 연결**: 플러그인 설치 → 로그인 → 장비 등록 → 끝
- **경량 통신**: MQTT 기반 상태 전송(브로커 호스트만 입력)

---

## ⚡ 빠른 설치(5–10분)

> 스크린샷 예시는 `docs/` 폴더에 넣고 경로만 맞춰주세요.

### 1) 회원가입

1. 접속: https://factor.io.kr  
2. 우측 상단 **로그인** → 창에서 **회원가입**  
3. 이메일·사용자명·비밀번호 입력 → **Sign Up**  
4. 메일함의 **인증 링크 클릭** → 완료

![step1](docs/1단계.png)

---

### 2) 플러그인 설치 (OctoPrint)

1. 우측 상단 **스패너(Settings)** → **Plugin Manager**  
2. **Get More… → …from URL**  
3. 아래 주소 붙여넣기 → **Install** → 완료 후 **OctoPrint 재시작**
![step2](docs/step2.png)  
![step3_install](docs/step3_install.png)

---

### 3) 플러그인 실행 (로그인)

- 좌측 메뉴 **FACTOR MQTT** 열기 → **이메일/비밀번호 로그인**

![step4_login](docs/step4_login.png)

---

### 4) 등록 & 연결

1. **프린터 연동**: `신규 등록` 그대로 두고 **생성** → 장비 정보 확인  
2. **카메라 연동(선택)**: 기존 Classic Webcam 등에서 쓰던 **스트림 URL 입력** → **저장**  
   - 예) `http://<라즈베리IP>:8080/stream` (MJPEG)  
   - WebRTC/RTSP/HLS 예시:
     - WebRTC: `http://<도메인 또는 IP>:8889/<카메라이름>`
     - RTSP: `rtsp://<도메인 또는 IP>:8554/<카메라이름>`
     - HLS: `http://<도메인 또는 IP>:8888/<스트림>.m3u8`
3. **MQTT 설정**:  
   - 브로커 호스트: `factor.io.kr` / 포트: `1883`  
   - **연결 테스트** → “연결됨” 확인 후 **Save**
4. 우측 **등록** 버튼으로 마무리

![step4_register](docs/step4_register.png)  
![step4_mqtt](docs/step4_mqtt.png)

---

## 🔧 환경/설정 팁

- **브라우저 보안**: HTTPS 페이지에서 **비보안(MJPEG/RTSP 등)** 스트림은 차단될 수 있어 **HTTPS/WSS** 권장  
- **Supabase 인증 리다이렉트**:
  - 대시보드: *Authentication → URL Configuration*  
  - **Site URL**: `https://factor.io.kr`  
  - **Additional Redirect URLs**: `https://factor.io.kr/auth/callback` 등 실제 콜백 경로 추가
- **코드에서 이메일 인증 링크 지정(선택)**:
  ```ts
  const { data, error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
  });