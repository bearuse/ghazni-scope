# FreeRTOS에 Ghazni Scope 붙이기

이 문서는 여러분의 FreeRTOS 프로젝트에서 Ghazni Scope로 태스크·큐·세마포어·mutex·이벤트 그룹·인터럽트를 보는 방법을 처음부터 끝까지 설명합니다. 이 저장소의 두 예제(`examples/freertos-posix`, `examples/freertos-mps2`)가 아래 단계를 그대로 따르고 있으니, 막히면 예제를 열어 비교해 보세요.

## 1. 어떻게 동작하나

```
FreeRTOS 커널 ── trace 매크로 ──▶ 기록기(scope_freertos.c) ── RAM 링(2048개) ──▶ "tracer" 태스크
                (문맥 전환, 큐, mutex ...)   이벤트 하나 16바이트                  10 ms마다 압축해서
                                                                                   scope_port_write()
                                                                                        │ UART 등
PC: ghazni-scope ◀──────────────────────────────────────────────────────────────────────┘
      └─▶ 브라우저 http://localhost:8800
```

1. FreeRTOS는 소스 곳곳에 `traceTASK_SWITCHED_IN()`, `traceQUEUE_SEND()` 같은 **빈 매크로**를 두고 있습니다. `scope_freertos.h`가 이 매크로들을 기록기 함수 호출로 바꿉니다. 그래서 FreeRTOS 소스를 한 줄도 고치지 않습니다.
2. 기록기 함수는 인터럽트를 잠깐 막고 16바이트 이벤트 하나를 RAM 링에 넣는 일만 합니다(시각, 종류, 태스크, 객체, 값). 보내는 일은 하지 않습니다.
3. 우선순위가 낮은 `tracer` 태스크가 10 ms마다 링을 비워 압축하고(이벤트 하나에 평균 3~5바이트), COBS로 감싸 `scope_port_write()`로 내보냅니다. 태스크 이름·객체 이름은 바뀔 때와 1초마다, 태스크별 통계(CPU 시간, 스택)는 100 ms마다 보냅니다.
4. 링이 가득 차면(tracer가 따라가지 못하면) 새 이벤트를 버리고 개수를 셉니다. 다음 프레임에 "몇 개 잃었다"가 실려 화면 위쪽 **유실**에 나옵니다. 조용히 사라지는 이벤트는 없습니다.

화면에서 `tracer` 태스크는 처음에 숨겨져 있습니다(관측 도구 자신의 활동이므로). 오른쪽 액터 목록에서 클릭하면 보입니다.

## 2. 준비물

- FreeRTOS **V11.x** (V11.3.3에서 시험). V10은 매크로 몇 개의 인자가 달라 시험하지 않았습니다.
- 타깃에서 PC로 바이트를 보낼 길: UART가 가장 흔합니다(921600 baud 이상 권장). USB CDC, TCP, 파일, 표준 출력도 됩니다.
- 시각을 잴 타이머: 가능하면 1 µs보다 고운 것(Cortex-M3/M4/M7이면 DWT 사이클 카운터).
- PC: Python 3.8 이상과 `ghazni-scope` 명령 (설치는 README의 'PC 도구 설치'). 시리얼 포트로 받으려면 pyserial도.

## 3. 단계별로

### 3.1 파일을 빌드에 넣기

| 넣을 것 | 무엇 |
|---|---|
| `targets/freertos/scope_freertos.c` | 기록기 (C 파일은 이것 하나) |
| 인클루드 경로 `targets/freertos/` | `scope_freertos.h`(매크로), `scope_port.h`(여러분이 구현할 함수) |
| 인클루드 경로 `include/` | `scope_proto.h`(형식), `scope_encode.h`(압축·COBS, 헤더만) |
| 여러분의 포트 파일 (예: `scope_port.c`) | 아래 3.3 |

Makefile이라면 이렇게 됩니다(`SCOPE`는 이 저장소를 둔 곳).

```make
CFLAGS += -I$(SCOPE)/include -I$(SCOPE)/targets/freertos
SRCS   += $(SCOPE)/targets/freertos/scope_freertos.c scope_port.c
```

STM32CubeIDE, MCUXpresso 같은 IDE에서는 위 두 폴더를 "Include paths"에, `scope_freertos.c`와 포트 파일을 소스에 추가하면 됩니다. libc는 `string.h`의 `memcpy`, `memset`, `strlen`, `strncmp`, `strncpy`만 씁니다(printf는 쓰지 않음).

### 3.2 FreeRTOSConfig.h

```c
/* ... 여러분의 기존 설정 ... */

/* Ghazni Scope */
#define configUSE_TRACE_FACILITY                1   /* 필수: 태스크·큐 번호를 씀 */
#define configRECORD_STACK_HIGH_ADDRESS         1   /* 권장: 통계에 스택 크기 */
#define INCLUDE_xTaskGetCurrentTaskHandle       1   /* 필수 */
#define INCLUDE_xTaskGetSchedulerState          1   /* 필수 */
#define INCLUDE_xTaskDelayUntil                 1   /* 필수: tracer 태스크가 씀 */
#define INCLUDE_uxTaskGetStackHighWaterMark     1   /* 권장: 통계에 스택 사용량 */
#define configQUEUE_REGISTRY_SIZE               16  /* 권장: 큐·세마포어 이름 */

#include "scope_freertos.h"     /* 반드시 맨 끝에 */
```

- `#include "scope_freertos.h"`는 **반드시 파일 맨 끝**, 다른 설정을 모두 정의한 뒤에 둡니다. 이 헤더가 `traceXXX` 매크로를 정의하므로, 여러분이 이미 `traceXXX`를 쓰고 있었다면 겹치는 것을 지워야 합니다(컴파일러가 "redefined" 경고를 냅니다).
- `configUSE_TRACE_FACILITY`가 1이 아니면 `#error`로 알려 줍니다.
- 기록기는 태스크 번호(`vTaskSetTaskNumber`)와 큐 번호(`vQueueSetQueueNumber`)를 자기 표 번호로 씁니다. 여러분의 코드가 이 번호를 따로 쓰고 있다면 충돌합니다.

### 3.3 포트 함수 세 개

`scope_port.h`에 선언된 세 함수를 여러분의 보드에 맞게 씁니다.

```c
#include "scope_port.h"

uint64_t scope_port_time(void);                         /* 계속 늘어나는 시각 */
uint64_t scope_port_hz(void);                           /* 그 시각의 1초당 눈금 수 */
void scope_port_write(const uint8_t *buf, size_t n);    /* PC로 바이트 보내기 */
```

**시각.** 인터럽트가 막힌 상태에서, 태스크와 인터럽트 양쪽에서 불립니다. 되돌아가면 안 됩니다(64비트로 늘려 주세요). Cortex-M3/M4/M7에서는 DWT 사이클 카운터가 가장 쉽고 정확합니다.

```c
#define DEMCR       (*(volatile uint32_t *)0xE000EDFC)
#define DWT_CTRL    (*(volatile uint32_t *)0xE0001000)
#define DWT_CYCCNT  (*(volatile uint32_t *)0xE0001004)

void scope_port_init(void)                  /* main()에서 scope_init() 전에 */
{
    DEMCR |= 1u << 24;                      /* TRCENA */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1;                          /* CYCCNTENA */
}

uint64_t scope_port_time(void)              /* 32비트 카운터를 64비트로 늘림 */
{
    static uint32_t last, high;
    uint32_t now = DWT_CYCCNT;
    if (now < last)                         /* 한 바퀴 돎 (168 MHz면 25초마다) */
        high++;
    last = now;
    return ((uint64_t)high << 32) | now;
}

uint64_t scope_port_hz(void) { return configCPU_CLOCK_HZ; }
```

이 방식은 25초(168 MHz 기준) 안에 한 번 이상 불려야 바퀴 수를 놓치지 않는데, tracer가 10 ms마다 깨어나 이벤트를 만들므로 문제가 없습니다. Cortex-M0/M0+처럼 DWT가 없는 칩, QEMU(DWT를 흉내 내지 않음)에서는 SysTick 값과 틱 수를 합쳐 씁니다: `examples/freertos-mps2/port.c`를 보세요.

**보내기.** `tracer` 태스크에서만 불립니다. 다 보낼 때까지 기다려도 됩니다(blocking). 가장 간단한 UART 예:

```c
void scope_port_write(const uint8_t *buf, size_t n)
{
    while (n--) {
        while (!(USART2->SR & USART_SR_TXE)) {}     /* STM32 예: 보낼 자리가 날 때까지 */
        USART2->DR = *buf++;
    }
}
```

UART 대신 **디버그 프로브(RTT)**로 보낼 수도 있습니다. UART가 필요 없고 더 빠릅니다: [RTT.md](RTT.md).

UART를 printf 콘솔과 같이 써도 됩니다. 프레임은 `0x01` … `0x00`으로 감싸여 있고, PC 도구가 그 밖의 글자는 콘솔 글로 보여 줍니다(Console 화면, 터미널). 다만 **다른 태스크의 printf가 프레임 중간에 끼어들면 안 되므로**, 콘솔 출력과 `scope_port_write`가 같은 mutex로 UART를 나눠 쓰게 하세요. DMA를 쓴다면 `scope_port_write`에서 전송이 끝날 때까지 기다리거나, 버퍼를 복사한 뒤 돌아오면 됩니다(같은 버퍼를 다음 호출에서 다시 씁니다).

### 3.4 main()

```c
int main(void)
{
    board_init();
    scope_port_init();              /* 여러분의 시각 준비 (있으면) */
    scope_init();                   /* tracer 태스크를 만듦: 스케줄러 시작 전에 */
    scope_isr_name(1, "uart_rx");   /* 인터럽트 이름 (아래 3.5) */

    xTaskCreate(...);               /* 여러분의 태스크들 */
    vTaskStartScheduler();
}
```

`scope_init()`은 `vTaskStartScheduler()` 전이면 언제 불러도 됩니다. 태스크와 객체는 만들어지는 순간 trace 매크로로 기록되므로, `scope_init()`보다 먼저 만든 것도 이름이 그대로 나옵니다. `scope_init()`이 하는 일은 tracer 태스크를 만들고 시각의 기준점(화면의 0초)을 정하는 것입니다.

### 3.5 인터럽트 (선택)

FreeRTOS는 인터럽트가 들어오고 나가는 지점에 매크로가 없으므로, 보고 싶은 인터럽트 처리기의 처음과 끝에 한 줄씩 넣습니다.

```c
void USART2_IRQHandler(void)
{
    scope_isr_begin(1);             /* 번호는 아무거나 (0~65535), 이름표와 맞추기만 */
    BaseType_t woken = pdFALSE;
    /* ... xQueueSendFromISR(rx_queue, &c, &woken); ... */
    scope_isr_end(1);
    portYIELD_FROM_ISR(woken);
}
```

화면에는 인터럽트마다 열이 생기고 처리 시간이 막대로 그려집니다. Statistics Report 아래 표에 횟수·평균·최대·CPU %가 나옵니다. 처리기 안에서 준 세마포어나 보낸 큐 메시지가 어느 태스크를 깨웠는지도 화살표로 이어집니다. 이름은 `scope_isr_name(번호, "이름")`으로, 최대 8개(`SCOPE_MAX_IRQS`)까지 붙입니다.

### 3.6 객체 이름 (권장)

큐·세마포어·mutex는 FreeRTOS의 큐 레지스트리에 넣은 이름이 그대로 쓰입니다.

```c
QueueHandle_t samples = xQueueCreate(8, sizeof(uint32_t));
vQueueAddToRegistry(samples, "samples");

SemaphoreHandle_t bus_lock = xSemaphoreCreateMutex();
vQueueAddToRegistry(bus_lock, "bus_lock");
```

이벤트 그룹은 레지스트리가 없으므로 `scope_name_object(핸들, "이름")`을 씁니다. 이름을 주지 않으면 `q0`, `mtx1`, `sem2`, `grp4` 같은 기본 이름(종류 + 번호)이 붙습니다. 이름은 15자까지 보입니다.

### 3.7 사용자 이벤트 (선택)

| 함수 | 화면 |
|---|---|
| `scope_user(채널, 값)` | User Events: 채널(0~255)마다 값 그래프. 센서 값, 큐 길이, 오차 등 |
| `scope_printf(채널, "형식", ...)` | User Events의 글 띠와 표. `%d %u %x %s %c`만 지원, 127자까지 |
| `scope_print(채널, "글")` | 위와 같고 서식 없음 |
| `scope_state(기계, "상태")` | State Machines: 상태 기계(0~63)마다 상태 타임라인과 머문 시간 |

모두 태스크에서 부릅니다(인터럽트에서도 동작하지만 글은 4바이트 조각 여러 개가 되므로 짧게). 기록이 빠른 대신 글은 링을 많이 씁니다: 글 4바이트마다 이벤트 하나(16바이트).

### 3.8 PC에서 보기

```sh
ghazni-scope --serial /dev/ttyUSB0 --baud 921600     # Windows: --serial COM5
```

브라우저에서 <http://localhost:8800>을 엽니다. 그 밖의 연결 방법:

| 연결 | 명령 |
|---|---|
| 시리얼 | `--serial /dev/ttyUSB0 --baud 921600` |
| 표준 출력으로 내보내는 프로그램(POSIX 포트, QEMU `-serial stdio`) | `--exec "프로그램과 인자"` |
| TCP로 바이트를 주는 곳(QEMU `-serial tcp:...`, ser2net, 보드의 TCP 서버) | `--tcp 호스트:포트` |
| 저장한 기록 | `--replay 파일` |

옵션 전체와 화면 쓰는 법은 [GUIDE.md](GUIDE.md)에 있습니다.

## 4. 무엇이 기록되나

| FreeRTOS에서 일어난 일 | Scope 이벤트 | 화면 |
|---|---|---|
| 문맥 전환 | switch (+ 나가는 태스크가 멈춘 이유) | 실행 구간, 막힘 선 |
| 태스크가 준비됨 | wake | 준비 대기 띠, 깨어남 지연 |
| `xQueueReceive`, `xSemaphoreTake`에서 막힘 | switch arg: recv + 객체 | `recv samples`, `lock bus_lock`(mutex), `take isr_sem`(세마포어) |
| `xQueueSend`에서 막힘(큐가 가득) | switch arg: send + 객체 | `send → samples` |
| `xEventGroupWaitBits`, `xEventGroupSync`에서 막힘 | switch arg: wait + 객체 | `wait flags` |
| `ulTaskNotifyTake`, `xTaskNotifyWait`에서 막힘 | switch arg: wait | `wait` |
| `vTaskDelay`, `xTaskDelayUntil` | switch arg: sleep | `sleep` |
| `vTaskSuspend`, `vTaskDelete` | stopped, exited | |
| 큐에 보냄, 세마포어·mutex 줌 (ISR 포함) | signal (큐: 보낸 뒤 쌓인 개수) | 깃발, 객체 열, 화살표(누가 누구를 깨웠나) |
| 큐에서 받음, 세마포어 가져감, mutex 잡음 | take (남은 개수) | 객체 열(mutex는 잡은 구간 막대) |
| 이벤트 그룹 비트 설정, 기다리던 비트를 받음 | signal(비트), take | |
| 타임아웃 | timeout | |
| 우선순위 상속·되돌림, `vTaskPrioritySet` | prio | "low priority 1 → 5 (inherited)" |
| `pvPortMalloc`, `vPortFree` (heap_1~5) | heap | Memory Heap |
| 태스크 생성 | 이름, 우선순위, 스택 범위 | 열 이름, 통계 |
| `scope_isr_begin/end` | irq, irqend | 인터럽트 열, 처리 시간 |

기록하지 않는 것: 소프트웨어 타이머 콜백 하나하나(타이머 태스크의 실행 구간으로 보임), 스트림 버퍼·메시지 버퍼의 내용(그것을 기다리는 태스크는 `wait`으로 보임), 커널 안에서 쓴 시간(Ghazni와 달리 Statistics Report의 커널 시간 열은 `–`).

## 5. 비용

Cortex-M3(clang -O2)에서 잰 값입니다.

| 항목 | 크기 |
|---|---|
| 코드 | 약 8.7 KB |
| RAM | 약 39 KB: 이벤트 링 32 KB(2048개 × 16 B) + 프레임 버퍼 약 6 KB + 표 |
| tracer 태스크 스택 | `configMINIMAL_STACK_SIZE * 4` 워드 (예제에서 실제 사용 276 B) |

RAM이 빠듯하면 링을 줄이세요. 컴파일러 옵션으로 정합니다(2의 거듭제곱):

```make
CFLAGS += -DSCOPE_RING_EVENTS=512        # 8 KB: tracer가 10 ms마다 비우므로 초당 수만 개까지는 충분
```

| 설정 (`-D`로 바꿈) | 기본값 | 뜻 |
|---|---|---|
| `SCOPE_RING_EVENTS` | 2048 | 링 크기(이벤트 수, 2의 거듭제곱) |
| `SCOPE_PERIOD_MS` | 10 | tracer가 깨어나는 간격 |
| `SCOPE_TASK_PRIO` | `tskIDLE_PRIORITY + 1` | tracer 우선순위 |
| `SCOPE_TASK_STACK` | `configMINIMAL_STACK_SIZE * 4` | tracer 스택(워드) |
| `SCOPE_MAX_TASKS` | 32 | 기록할 수 있는 태스크 수 |
| `SCOPE_MAX_OBJECTS` | 32 | 큐·세마포어·mutex·이벤트 그룹 수 |
| `SCOPE_MAX_IRQS` | 8 | 이름 붙일 인터럽트 수 |

**시간 부담.** 이벤트 하나를 기록하는 데 인터럽트를 막고 시각을 읽고 16바이트를 쓰는 정도(수십 사이클)가 듭니다. 보내는 일은 tracer가 합니다. QEMU Cortex-M3 예제(초당 이벤트 약 3800개, UART)에서 tracer는 CPU의 약 2.5 %를 썼습니다(화면 위쪽 **Scope 부하**). QEMU는 실제 칩의 속도를 흉내 내지 않으므로 실제 보드에서는 다를 수 있습니다. 화면의 Scope 부하가 여러분 보드에서 잰 실제 값입니다.

**대역폭.** 이벤트 하나가 압축 후 평균 3~5바이트입니다. 921600 baud(초당 약 92 KB)면 초당 2만 개 정도까지 보낼 수 있습니다. 그보다 많으면 링이 차서 유실이 생기고 화면에 표시됩니다. 우선순위가 낮은 tracer가 CPU를 오래 못 받아도 같은 일이 생깁니다. 이럴 때는 `SCOPE_TASK_PRIO`를 올리거나 링을 키우세요.

## 6. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 화면이 비어 있음, 터미널에 깨진 글자 | baud가 양쪽에서 같은지. `scope_init()`을 불렀는지. tracer가 돌고 있는지(더 높은 우선순위 태스크가 CPU를 놓지 않으면 tracer가 못 돎) |
| `Ghazni Scope needs configUSE_TRACE_FACILITY 1` | FreeRTOSConfig.h에 그 줄을 넣고, `#include "scope_freertos.h"`가 맨 끝인지 |
| `traceXXX redefined` 경고 | 이미 쓰던 trace 매크로나 다른 트레이서(Tracealyzer, SystemView)와 겹침. 하나만 쓰세요 |
| 유실이 계속 늘어남 | 대역폭(위 5), tracer 우선순위, 링 크기 |
| 시간이 이상함(막대가 겹치거나 거꾸로) | `scope_port_time`이 되돌아가지 않는지, `scope_port_hz`가 맞는지 |
| 큐 이름이 `q0` | `vQueueAddToRegistry`와 `configQUEUE_REGISTRY_SIZE` > 0 |
| 태스크가 33개 이상 | `-DSCOPE_MAX_TASKS=64` (최대 252) |
| idle 태스크가 보이지 않음 | 정상: idle은 "idle" 체크 상자로 봄(CPU가 놀고 있는 시간) |

## 7. 제한

- 멀티코어(SMP) FreeRTOS(`configNUMBER_OF_CORES` > 1)는 코어 번호를 기록하도록 만들었지만 시험하지 않았습니다.
- FreeRTOS V10 이하는 시험하지 않았습니다(V10.4 이후라면 대부분 동작할 것으로 보지만 매크로 인자가 다른 것이 있습니다).
- 기록기는 스트리밍만 합니다. "멈춘 뒤 마지막 N개를 꺼내 보기"(스냅숏) 방식은 없습니다.

## 8. 예제 살펴보기

`examples/common/demo.c`는 화면의 각 기능이 드러나도록 만든 태스크 묶음입니다.

| 태스크 (우선순위) | 하는 일 | 화면에서 볼 것 |
|---|---|---|
| producer (2) | 큐 `samples`에 값을 보냄: 5 ms마다, 40개 중 10개는 1 ms마다 몰아서(큐가 참). 10개마다 센서 값 `scope_user(1, …)` | User Events ch1, 큐에 쌓인 개수 |
| consumer (3) | 큐에서 받아 `pvPortMalloc`, 3 ms 쉬고 `vPortFree`. 50개마다 `scope_printf` | `recv samples`, Memory Heap, 글 띠 |
| low (1) / mid (4) / high (5) | 500 ms마다: low가 mutex `bus_lock`을 잡고 30 ms 바쁨, 10 ms 뒤 high가 같은 mutex를 원함, 15 ms 뒤 mid가 50 ms 바쁨 | `lock bus_lock`, low의 우선순위 1 → 5 → 1(상속 덕분에 mid가 끼어들지 못함), 세마포어 `done` |
| controller (2) / worker (3) | controller가 40 ms마다 상태 기계(IDLE → MEASURE → SEND)를 한 칸씩 돌고, SEND에서 이벤트 그룹 `flags`에 비트 0x3 설정. worker가 그 비트를 기다렸다가 2 ms 일함 | State Machines, `wait flags` |
| isr_handler (6) | 20 ms마다 오는 인터럽트(`tick20`)가 주는 세마포어 `isr_sem`을 기다림 | 인터럽트 열, 처리 시간, `take isr_sem` |

- `examples/freertos-posix`: FreeRTOS를 Linux 프로세스로 돌립니다(공식 POSIX 포트). 인터럽트는 틱 훅으로 흉내 냅니다. 프레임은 표준 출력으로 나가고, `make run`이 `--exec`로 받습니다. 하드웨어 없이 Scope를 익히기에 좋습니다. 시간은 Linux의 시각이라 Linux 스케줄러 때문에 가끔 튑니다.
- `examples/freertos-mps2`: Cortex-M3 보드(ARM MPS2 AN385)를 QEMU에서 돌립니다. UART0으로 내보내고(`-serial stdio`), 하드웨어 타이머 TIMER0 인터럽트가 20 ms마다 들어옵니다. 실제 보드로 옮길 때 바꿀 곳은 `port.c`(UART, 시각), `startup.c`(벡터 표), `mps2.ld`(메모리 배치)입니다.
