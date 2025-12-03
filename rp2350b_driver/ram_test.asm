
    org 100h

RAM_START equ 16384
; ((($-1) | 0xff) + 1)
RAM_END equ 0ffffh
RAM_LEN equ (RAM_END+1) - RAM_START


    ld de, 0ff00h
    call do_test

    ; ld de, 0aa55h
    ; call do_test

    ; ld de, 055aah
    ; call do_test

    di
    halt

do_test:
    push de
    ld ix, 0
    add ix, sp
    ld (ix+0), high RAM_START
    ld (ix+1), 64

repeat_test:
    bit 0, (ix+1)
    ld a, d
    jr z, .not_inverse
    xor 0xff
.not_inverse:
    call fill_all

    ld c, a
    ld b, high RAM_LEN
    ld hl, RAM_START
    call check_ram

    ld a, (ix+0)
    and 0xf
    add a, '0'
    cp '9'
    jr c, .digit_ok
    add 'A'-'0'-10

.digit_ok:
    ld (str_okN), a

    ld hl, str_ok
    call pr_str

    dec (ix+1)
    jr nz, repeat_test

    pop de
    ret

str_ok:  db "test stale "
str_okN: db '?'
         db " ok", 0ah, 0dh, 0

pr_str:
    push bc
    ld bc, 0ff83h
.l: ld a, (hl)
    or a
    jr z, .done
    out (c), a
    inc hl
    jr .l
.done:
    pop bc
    ret

check_ram:
    ; hl - addr, b - pages, c - expected value
    ; z - ok nz fail
    ld a, (hl)
    cp c
    ret nz
    inc l
    jr nz, check_ram
    inc h
    djnz check_ram
    ret

fill_all:
    ld hl, RAM_START
    ld b, high (RAM_END - RAM_START)
.l1:
    call fill_page
    inc h
    djnz .l1
    ret

;     ld hl, RAM_START
;     ld b, high (RAM_END - RAM_START)
;     ld c, 0x55
; .l2:
;     ld l, 0
;     call check_page
;     jr nz, page_fail
;     inc h
;     djnz .l2

;     exx
;     ld bc, 0x2
;     exx

;     ld hl, RAM_START
; loop_ram:
;     exx
;     ld hl, test_tab
;     add hl, bc
;     ld a, (hl)
;     exx

;     call fill_page

;     ld a, high RAM_END
;     cp h
;     jr nz, loop_ram

; page_fail:
;     ld a, h
;     and a, 0xf0
;     rra
;     rra
;     rra
;     rra
;     add a, '0'
;     ld (str_page_fail_h), a
;     ld a, h
;     and a, 0x0f
;     add a, '0'
;     ld (str_page_fail_l), a

;     ld de, str_page_fail
;     ld c, 9
;     call bdos
;     ret

; str_page_fail: db "page "
; str_page_fail_h: db '?'
; str_page_fail_l: db '?'
;     db " failed", '$', 0

; hl addr
; a fill value
fill_page:
    ld (hl), a
    inc l
    jr nz, fill_page
    ret

; c value
; hl start
; returns: zflag 0 ok, 1 fail
check_page:
    ld a, (hl)
    cp c
    ret nz
    inc l
    jr nz, check_page
    ret

bdos:
    push af
    push hl
    call 5
    pop hl
    pop af
    ret

    ds 64 
    align 256
_stack equ $