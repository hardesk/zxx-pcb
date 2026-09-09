	org 08000h
	jp start
hello_msg2: ds hello_msg_len
start:
	ld hl, 0 
	ld sp, hl

	ld ix, -4
	add ix, sp
	ld sp, ix
	ld (ix+3), 16

; loop2:
; 	ld de, hello_msg2
; 	ld hl, hello_msg
; loop1:
; 	ld a, (hl)
; 	ld (de), a
; 	inc de
; 	inc hl
; 	or a, a
; 	jr nz, loop1

; 	ld c, 9
; 	ld de, hello_msg2
; 	call bdos

; 	dec (ix+3)
; 	jr nz, loop2
	
	ld c, 9
	ld de, testing_msg
	call bdos

	; test RLC instruction

.loop_regs:
	ld a, (test_INSTR+3)
	and 07h
	add a, '0'
	ld (rlc_msg_R), a
	ld c, 9
	ld de, rlc_msg
	call bdos

	ld iy, test_inst_data


	ld a, (test_INSTR+3)
	inc a
	and 7
	; ld c, a
	; and 0f8h
	; ld b, a
	; inc c
	; ld a, c
	; and 7
	; or b
	ld (test_INSTR+3), a
	add a, 'A'
	ld c, 2
	ld e, a
	call bdos

	; ld a, c
	; and 7
	ld a, (test_INSTR+3)
	or a
	jr nz, .loop_regs

	ld hl, 4
	add hl, sp
	ld sp, hl

	ld c, 9
	ld de, testdone_msg
	call bdos

deadend:
	di
	halt
	jp deadend

test_INSTR:
	rlc (iy+0), b

testing_msg db 'testing RLO!', 0ah,0dh,0
testdone_msg db 'testing DONE. HALT', 0ah, 0dh, 0


rlc_msg db 'rlc (iy+0), <'
rlc_msg_R	db 'X'
		db '>', 0ah, 0dh, 0
	
test_inst_data db 0

bdos:
	push af
	push bc

	if 1
	ld a, c
	ld bc, 0ff83h
	cp 9
	jr z, bdos_9
	cp 2
	jr nz, bdos_e
	out (c), e
	jr bdos_e
bdos_9:
	ld a, (de)
	out (c), a
	inc de
	or a
	jr nz, bdos_9
bdos_e:

	else

	push	de
	push	hl
	call	5
	pop	hl
	pop	de
	endif

	pop	bc
	pop	af

	ret

hello_msg: db 'Hello World!', 0ah, 0dh, 0
hello_msg_len equ $-hello_msg
	