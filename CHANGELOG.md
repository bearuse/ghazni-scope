# 변경 이력

## 0.2.0

**독립 설치 패키지**
- PC 도구를 Python 패키지 `ghazni_scope`로 (`host/` → `ghazni_scope/`). `pipx install git+https://github.com/bearuse/ghazni-scope`로 설치하면 `ghazni-scope` 명령이 생김. 설치하지 않고 저장소에서 `python3 -m ghazni_scope`로도 실행. 시리얼은 `[serial]` 추가 설치(pyserial)
- `ghazni-scope --version`
- 예제 `make run`은 저장소의 패키지를 씀(`SCOPE=ghazni-scope`로 설치된 것)
- CI: 저장소에서 바로 돌린 시험에 더해, pipx로 설치한 패키지로 같은 시험(웹 페이지가 패키지에 들어 있는지 포함)
- 스크린샷 17장(`screenshots/`), 실시간 화면 중복 항목 수정, FreeRTOS 기록기·화면 문구 수정 (PR #1)

## 0.1.0

- 첫 판: Ghazni 저장소에서 분리한 PC 도구와 화면, RTOS와 무관한 스트림 형식 헤더, FreeRTOS V11 기록기, Linux(POSIX)·Cortex-M3(QEMU) 예제와 시험, 문서
