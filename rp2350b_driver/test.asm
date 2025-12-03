	org 100h
	jp start
hello_msg2: ds hello_msg_len
start:
	ld hl, 0ffffh 
	ld sp, hl

	ld ix, -4
	add ix, sp
	ld sp, ix
	ld (ix+3), 16

loop2:
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
	call bdos

	dec (ix+3)
	jr nz, loop2

	ld hl, 4
	add hl, sp
	ld sp, hl

deadend:
	di
	halt
	jp deadend
	

bdos:
	push	af
	push	bc
	push	de
	push	hl
	call	5
	pop	hl
	pop	de
	pop	bc
	pop	af
	ret

hello_msg: db 'Hello World!', 0ah, 0dh, '$', 0
hello_msg_len equ $-hello_msg
	