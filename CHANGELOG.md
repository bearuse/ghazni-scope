# 변경 이력

## 0.5.1

- 힙: 할당·해제 하나는 이벤트 두 개(크기, 주소)이고 도구가 태스크별로 짝을 지었는데, CPU가 둘이면 두 CPU의 idle 태스크(그리고 스케줄러 시작 전의 코드)가 같은 번호라 두 CPU의 반쪽이 엇갈려 짝이 틀렸음 → 할당 하나가 사라지고 그 해제가 '모르는 블록 해제' 경고로. 이제 태스크와 CPU로 짝을 지음. 기록기는 두 반쪽을 인터럽트를 막은 채 붙여 씀. ESP32 CI에서 가끔 실패하던 원인(0.5.0의 '최근 20 ms 미루기'는 이것을 고치지 못했음)
- 사용 매뉴얼 PDF(`docs/pdf/Ghazni-Scope-Manual.pdf`, `make manual-pdf`)

## 0.5.0

**ESP32 (ESP-IDF)** ([docs/ESP-IDF.md](docs/ESP-IDF.md))
- 컴포넌트 `targets/esp-idf/ghazni_scope`: 프로젝트에 `EXTRA_COMPONENT_DIRS` 한 줄과 `CONFIG_FREERTOS_USE_TRACE_FACILITY=y`. trace 매크로를 ESP-IDF의 FreeRTOS에 `-include`로 넣음(그쪽 FreeRTOSConfig.h는 고칠 수 없음), `esp_timer` 시계, UART0, 힙 훅(`CONFIG_HEAP_USE_HOOKS`)
- 기록기: CPU마다 이벤트 링(각 CPU는 자기 링에만, CPU 사이 잠금 없음), tracer가 시각순으로 합침. `pxCurrentTCBs[CPU]`. ESP-IDF만의 `traceQUEUE_SEMAPHORE_RECEIVE`, `traceQUEUE_GIVE_FROM_ISR`. 한 차례에 그 순간까지 쌓인 것만 보냄(보내기가 이벤트를 만드는 UART 드라이버에서 끝없이 돌던 것). 프레임 버퍼 크기를 태스크·객체 수에서 계산(늘리면 넘치던 것)
- 도구: 크기 없는 해제(ESP-IDF의 훅)는 할당 때의 크기로
- 예제 `examples/esp-idf`(CPU 2개, 하드웨어 타이머 인터럽트): `make`(ESP-IDF 또는 Docker), `make run`(Espressif의 QEMU)
- 시험: `run_freertos.py esp32`(15가지 + 두 CPU, CPU 1에 묶은 태스크), CI에 ESP-IDF 이미지로
- 화면: Trace View의 레이블 두 개가 NaN으로 나오던 것(0.3.0의 영어 화면에서 생김) 고침, 브라우저 시험이 NaN·undefined를 잡음

## 0.4.0

**디버그 프로브로 받기 (RTT)** ([docs/RTT.md](docs/RTT.md))
- 타깃: `targets/rtt/scope_rtt.c` — SEGGER RTT와 같은 배치의 제어 블록과 버퍼 "Scope"(4 KB). J-Link, OpenOCD, pyOCD가 모두 읽음. `scope_port_write`를 이것으로
- PC: J-Link·OpenOCD의 RTT 서버는 `--tcp`로. `--rtt-gdb HOST:PORT --elf app.elf`는 아무 GDB 서버(OpenOCD, J-Link GDB Server, pyOCD, QEMU)로 버퍼를 직접 읽음(ELF에서 `_SEGGER_RTT`, 채널 이름·번호, 읽는 간격)
- 예제: `examples/freertos-mps2`의 `make rtt`, `make run-rtt`(QEMU의 GDB 서버가 프로브 역할)
- 시험: `run_freertos.py mps2-rtt`(RTT로 받은 스트림을 UART와 같은 15가지로, CI), 단위 시험(가짜 GDB 서버로 고리 버퍼가 한 바퀴 돈 경우)
- 실제 프로브와 보드에서는 아직 시험하지 않음

## 0.3.0

**영어 화면**
- 화면 전체를 영어로도 (브라우저 언어가 한국어가 아니면 영어). 오른쪽 위 `EN` / `한국어` 단추로 바꾸고 기억함
- 도구(서버)가 보내는 글은 영어로: 트리거 거부 이유, 기록 파일 오류. 트리거 적중 북마크는 화면이 자기 언어로 이름을 붙임(서버가 종류·이름·값을 따로 보냄)
- 시험: 영어 화면에서 화면 12개, 가로 보기, 선택, 구간 비교를 열어 한글이 하나도 없는지(캔버스에 그린 글 포함), 거부 이유·북마크가 영어인지, 단추로 한국어로 바뀌는지. 한국어 브라우저에서는 한국어
- README에 영어 안내(설치, 해 보기, FreeRTOS에 붙이기)와 영어 화면 캡처

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
