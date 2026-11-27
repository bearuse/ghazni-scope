# 디버그 프로브로 받기 (RTT)

UART 대신 **디버그 프로브**(J-Link, ST-Link, CMSIS-DAP 등)로 스트림을 받는 방법입니다. 보드에 UART를 따로 연결할 필요가 없고, 보통 UART보다 훨씬 빠릅니다. Percepio Tracealyzer와 SEGGER SystemView도 주로 이 방식을 씁니다.

## 1. RTT가 뭔가

RTT(Real-Time Transfer)는 SEGGER가 만든 간단한 약속입니다.

```
타깃 RAM ┌──────────────────────────────────────────┐
         │ "SEGGER RTT" 표지 + 버퍼 정보(제어 블록)  │ ◀── 프로브가 RAM을 직접 읽음
         │ 버퍼 "Scope" (4 KB 고리)                 │     (CPU를 거의 방해하지 않음)
         └──────────────────────────────────────────┘
            ▲ 타깃은 쓰고 쓴 위치(WrOff)를 올림           프로브는 읽고 읽은 위치(RdOff)를 올림
```

- 타깃은 RAM의 고리 버퍼에 바이트를 쓰기만 합니다. 레지스터를 만지거나 인터럽트를 쓰지 않습니다.
- 디버그 프로브는 CPU가 도는 동안 디버그 포트(SWD/JTAG)로 RAM을 읽습니다. RAM 어디에 버퍼가 있는지는 맨 앞의 `"SEGGER RTT"` 표지로 찾습니다.
- 그래서 J-Link, OpenOCD, pyOCD 같은 도구가 모두 이 버퍼를 읽을 수 있습니다.

## 2. 타깃 쪽

`targets/rtt/scope_rtt.c`(C 파일 하나, libc 없음)를 빌드에 넣고, `scope_port_write`를 UART 대신 이것으로 씁니다.

```c
#include "scope_rtt.h"

void scope_port_write(const uint8_t *buf, size_t n)
{
    while (n) {                                 /* 프로브가 읽어 갈 때까지 기다리며 */
        unsigned w = scope_rtt_write(buf, n);
        buf += w;
        n -= w;
        if (n)
            vTaskDelay(1);
    }
}
```

- 버퍼 이름은 `Scope`, 크기는 4 KB입니다(`-DSCOPE_RTT_SIZE=8192`로 바꿈). 프로브는 몇 ms마다 비웁니다.
- 프로브가 연결되지 않았으면 버퍼가 차고 `tracer` 태스크가 기다립니다. 그동안 이벤트 링이 넘치면 "유실"로 셉니다. 다른 태스크는 영향을 받지 않습니다.
- **이미 SEGGER의 RTT(`SEGGER_RTT.c`)를 쓰고 있다면** 이 파일을 넣지 마세요. 제어 블록이 두 개가 되면 도구가 헷갈립니다. 대신 `SEGGER_RTT_Write(1, buf, n)`처럼 **채널 하나를 Scope에 주고**(`SEGGER_RTT_ConfigUpBuffer(1, "Scope", ...)`), 받는 쪽에 그 채널을 알려 주세요.
- 캐시가 있는 칩(Cortex-M7 등)에서는 버퍼를 캐시하지 않는 RAM(DTCM 등)에 두세요. 프로브는 캐시를 거치지 않고 RAM을 읽습니다.

예제: `examples/freertos-mps2`의 `make rtt`가 같은 데모를 RTT로 내보내는 판을 만듭니다(`port.c`의 `SCOPE_RTT`).

## 3. PC 쪽: 세 가지 방법

### (가) 프로브 도구의 RTT 서버 → `--tcp` (권장)

J-Link와 OpenOCD는 RTT 버퍼를 읽어 TCP 포트로 내보내는 기능이 있습니다. CPU를 멈추지 않고 읽으므로 가장 좋습니다. Ghazni Scope는 그 포트에 붙기만 하면 됩니다.

**SEGGER J-Link**
```sh
JLinkGDBServer -device STM32F407VG -if SWD -speed 4000      # 또는 J-Link Commander로 연결해 둠
ghazni-scope --tcp localhost:19021                         # J-Link의 RTT 텔넷 포트
```
- J-Link의 RTT 텔넷 포트(기본 19021)는 **채널 0**을 내보냅니다. `scope_rtt.c`의 버퍼는 채널 0이라 그대로 됩니다. SEGGER RTT의 다른 채널을 Scope에 줬다면 아래 OpenOCD나 (다)를 쓰세요.

**OpenOCD** (ST-Link, CMSIS-DAP, J-Link 등)
```sh
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
  -c "init" -c "rtt setup 0x20000000 0x20000 \"SEGGER RTT\"" -c "rtt start" \
  -c "rtt server start 9090 0"                             # 0 = 채널 번호
ghazni-scope --tcp localhost:9090
```
- `rtt setup`의 두 숫자는 제어 블록을 찾을 RAM 범위(시작, 크기)입니다. 칩의 RAM에 맞추세요. `arm-none-eabi-nm demo.elf | grep _SEGGER_RTT`로 정확한 주소를 알 수 있습니다.

### (나) 아무 GDB 서버 → `--rtt-gdb`

Ghazni Scope가 GDB 서버를 통해 직접 버퍼를 읽습니다. OpenOCD(포트 3333), J-Link GDB Server(2331), pyOCD(`pyocd gdbserver`, 3333), QEMU(`-gdb`) 모두 됩니다.

```sh
pyocd gdbserver --target stm32f407vg &
ghazni-scope --rtt-gdb localhost:3333 --elf build/app.elf
```
- `--elf`: 타깃의 ELF 파일. 그 안의 `_SEGGER_RTT` 심볼로 제어 블록 주소를 찾습니다. ELF가 없으면 `--rtt-addr 0x20000008`.
- `--rtt-channel`: 버퍼 이름이나 번호(기본 `Scope`). SEGGER RTT의 채널 1을 줬다면 `--rtt-channel 1`.
- `--rtt-poll 10`: 몇 ms마다 읽을지.
- **주의**: GDB 서버로 메모리를 읽으려면 읽는 동안 CPU를 잠깐 멈춥니다(한 번에 약 0.5 ms, 10 ms마다). 그동안 타깃의 시간도 함께 멈추는 것이 아니라면(실제 칩의 타이머는 계속 감) 타이밍이 조금 흐트러집니다. 그래서 실제 보드에서는 (가)를 권합니다. (나)는 (가)가 안 되는 프로브, QEMU, 그리고 시험에 씁니다.
- 디버거(GDB)로 디버깅하는 중에는 같은 GDB 서버에 두 클라이언트가 붙을 수 없는 경우가 많습니다. 그때는 (가)를 쓰세요.

### (다) QEMU로 하드웨어 없이 해 보기

```sh
cd examples/freertos-mps2
make run-rtt          # QEMU의 GDB 서버가 프로브 역할: ghazni-scope --rtt-gdb ... --elf build-rtt/demo.elf
```

## 4. 확인한 것과 아직 못 한 것

- **확인함**: `tests/run_freertos.py mps2-rtt`가 Cortex-M3(QEMU)에서 RTT로 받은 스트림을 UART와 똑같은 15가지로 검사합니다(유실 0, 막힘 이유, 우선순위 상속, 인터럽트 ...). 단위 시험이 가짜 GDB 서버로 고리 버퍼가 한 바퀴 돌아 끝과 처음에 걸친 경우를 확인합니다. QEMU에서 한 번 읽는 데 약 0.5 ms, 초당 약 35 KB.
- **아직 못 함**: 실제 프로브(J-Link, ST-Link + OpenOCD, pyOCD)와 실제 보드에서는 시험하지 않았습니다. 위 명령은 각 도구의 문서대로 적은 것입니다. 해 보시고 안 되면 알려 주세요.
