# 변경 이력

## 0.2.1

- Trace View: 비스듬히 쓴 열 이름(태스크, 인터럽트, 객체)이 잘리지 않게 머리 부분 높이를 가장 긴 이름에 맞춤
- Memory Heap: 태스크 밖 할당(스케줄러 시작 전의 스택·큐)은 그래프에서 기본으로 뺌(체크 상자, 표에는 그대로). 태스크의 작은 할당이 보임
- Dependency Graph 설명을 보고 있는 OS에 맞게
- 시험: 브라우저 시험 `tests/test_ui.js`(Playwright, CI): 화면 12개가 오류 없이 그려지는지, 가로·CPU 열·어두운 화면·전체 보기, 열 이름이 머리에 들어가는지, 트리거, FreeRTOS 스트림에 Ghazni 전용 글이 없는지. 저장소 그대로와 설치한 패키지 둘 다

## 0.2.0

**독립 설치 패키지**
- PC 도구를 Python 패키지 `ghazni_scope`로 (`host/` → `ghazni_scope/`). `pipx install git+https://github.com/bearuse/ghazni-scope`로 설치하면 `ghazni-scope` 명령이 생김. 설치하지 않고 저장소에서 `python3 -m ghazni_scope`로도 실행. 시리얼은 `[serial]` 추가 설치(pyserial)
- `ghazni-scope --version`
- 예제 `make run`은 저장소의 패키지를 씀(`SCOPE=ghazni-scope`로 설치된 것)
- CI: 저장소에서 바로 돌린 시험에 더해, pipx로 설치한 패키지로 같은 시험(웹 페이지가 패키지에 들어 있는지 포함)
- 스크린샷 17장(`screenshots/`), 실시간 화면 중복 항목 수정, FreeRTOS 기록기·화면 문구 수정 (PR #1)

## 0.1.0

- 첫 판: Ghazni 저장소에서 분리한 PC 도구와 화면, RTOS와 무관한 스트림 형식 헤더, FreeRTOS V11 기록기, Linux(POSIX)·Cortex-M3(QEMU) 예제와 시험, 문서
