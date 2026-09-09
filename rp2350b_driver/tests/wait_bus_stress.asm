; Repeating, deterministic bus trace. Assemble at the firmware's load address.
; Consecutive reads of 4000 are intentional: an address deduplicator is wrong.
    org 0100h
start:
    ld a,055h
    ld (04000h),a
    ld a,(04000h)
    ld a,(04000h)
    cp 055h
    jp nz,fail
    ld a,0aah
    ld (04000h),a
    ld a,(04000h)
    cp 0aah
    jp nz,fail
    ld bc,0ff80h
    out (c),a
    in a,(c)
    cp 0bfh
    jp nz,fail
    ld bc,0ff82h
    out (c),a
    in a,(c)
    cp 0bfh
    jp nz,fail
    jp start
fail:
    ld a,0eeh
    ld (04001h),a
    halt
    jp fail
