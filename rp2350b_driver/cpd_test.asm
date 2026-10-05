    org 100h

    ld hl, s_start
    call pr_str

    ld hl, str_tab

.loop_tab:
    ld e, (hl)
    inc hl
    ld d, (hl)
    inc hl
    ld a, e
    or d
    jr z, .lend

    ld c, (hl)
    inc hl
    ld b, (hl)
    inc hl

    ex de, hl   ; hl - str start

    push hl
    call pr_str
    ld hl, s_nl
    call pr_str
    pop hl

    add hl, bc
    dec hl      ; hl - last char of str

    push bc
    push hl

.l1:
    ld a, 'x'
    cpd
    call pr_regs
    ld a, b
    or c
    jr nz, .l1

    ld hl, s_nl
    call pr_str

    pop hl
    pop bc

    ld a, 'x'
    cpdr
    call pr_regs

    ex de, hl   ; restore hl with str_tab pointer

    jr .loop_tab

.lend:
    jr .lend

str1 db "ab", 0
str2 db "ax", 0
str3 db "xa", 0
str4 db "x", 0
;str5 db "", 0

str_tab dw str1, 2
        dw str2, 2
        dw str3, 2
        dw str4, 1
        ;dw str5, 0
        dw 0

s_start db "Testing CPD, CPDR\r\n", 0
s_nl db "\r\n", 0

pr_regs:
    push af
    push hl

    push hl
    push de
    push bc
    push af

    ld hl, s_regsAF
    call pr_str
    pop hl
    call pr_hexHL

    ld hl, s_regsBC
    call pr_str
    pop hl
    call pr_hexHL

    ld hl, s_regsDE
    call pr_str
    pop hl
    call pr_hexHL

    ld hl, s_regsHL
    call pr_str
    pop hl
    call pr_hexHL

    ld hl, s_nl
    call pr_str

    pop hl
    pop af
    ret

s_regsAF db " af ", 0
s_regsBC db " bc ", 0
s_regsDE db " de ", 0
s_regsHL db " hl ", 0

; arg hl
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

; arg: a
pr_hexA:
    push bc
    push af
    ld bc, 0ff83h
    and 0f0h
    rra
    rra
    rra
    rra
    add a, '0'
    cp '9'+1
    jr c, .l1
    add a, 'A'-'0'-10
.l1:
    out (c), a
    pop af
    and 0fh
    add a, '0'
    cp '9'+1
    jr c, .l2
    add a, 'A'-'0'-10
.l2:
    out (c), a
    pop bc
    ret

; arg HL
pr_hexHL:
    ld a, h
    call pr_hexA
    ld a, l
    call pr_hexA
    ret
