	org 100h
	jp start
hello_msg2: ds hello_msg_len
start:
	ld de, hello_msg2
	ld hl, hello_msg
loop1:
	ld a, (hl)
	ld (de), a
	inc de
	inc hl
	or a, a
	jr nz, loop1

	ld c, 9
	ld de, hello_msg2
	ld a, 1
	ld (0), a

	ret

hello_msg: db 'Hello World!', 0
hello_msg_len equ $-hello_msg
	