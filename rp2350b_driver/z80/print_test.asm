
    org 0x8000

    ld hl, 0
    add hl, sp
    call pr_hexHL

    ld sp, 0

    ld a, '@'
    call pr_char

    ld a, 0xa
    call pr_char

    call pr_next
    db 'Hello from caller code\n', 0

    di
    halt

    call pr_next
    db 'Why are we here after DI:HALT ???\n', 0

m1: db 1

; check if rolling bit in mem works
test_roll:
    ld b, 8
.l1:
    ld a, (hl)
    rlc a
    ld (hl), a
    djnz .l1
    cp 0x80
    jr nz, .e1
    ld a, 1
    ret
.e1:
    xor a
    ret

r1: db 0x80

    include print.asm
