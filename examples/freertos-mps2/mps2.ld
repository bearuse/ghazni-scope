/* QEMU mps2-an385: 4 MiB code memory at 0, 4 MiB SRAM at 0x20000000 */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 4M
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 4M
}
ENTRY(Reset_Handler)
SECTIONS
{
    .text : {
        KEEP(*(.vectors))
        *(.text*) *(.rodata*)
        . = ALIGN(4);
    } > FLASH
    .ARM.exidx : { *(.ARM.exidx*) } > FLASH
    _sidata = LOADADDR(.data);
    .data : { _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT > FLASH
    .bss (NOLOAD) : { _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
    _estack = ORIGIN(RAM) + LENGTH(RAM);
}
