OUTC_PORT equ 0xff83 
    IFUSED pr_char
pr_char:
    push bc
    ld bc, OUTC_PORT
.loop:
    out (c), a
    pop bc
    ret
    ENDIF

    ifused pr_str
; hl str
pr_str:
    push bc
    ld bc, OUTC_PORT
.loop:
    ld a, (hl)
    inc hl
    out (c), a
    or a
    jr nz, .loop
    pop bc
    ret
    endif

    ifused pr_next
; print string that goes after the call to this function
pr_next:
    ex (sp), hl
    push bc
    ld bc, OUTC_PORT 
.loop:
    ld a, (hl)
    inc hl
    out (c), a
    or a, a
    jr nz, .loop
    pop bc
    ex (sp), hl
    ret
    endif

    ifused pr_hexA
; arg: a
pr_hexA:
    push bc
    push af
    ld bc, OUTC_PORT 
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
    endif

    ifused pr_hexHL
; arg HL
pr_hexHL:
    ld a, h
    call pr_hexA
    ld a, l
    jp pr_hexA
    endif
