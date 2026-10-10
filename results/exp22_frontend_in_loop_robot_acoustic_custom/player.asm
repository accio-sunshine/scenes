; PDM player: 4 data lines, one byte per clock period (bits 3:0 left mics, 7:4 right mics)
; CLK on R31.t0; data lines on R30[3:0]
start:
    ldi   r4, 0
    ldi   r5, 256
    ldi   r9, 4095
    ldi   r6, 0
    lbbo  &r10, r4, 16, 4
wait_host:
    lbbo  &r0, r4, 8, 4
    qbeq  wait_host, r0, 0
    wbs   r31.t0                 ; begin on a known clock phase
fetch:
    qbeq  done, r6, r10
    lbbo  &r7, r4, 0, 4
    qbeq  underrun, r7, r6
    and   r0, r6, r9
    add   r0, r0, r5
    lbbo  &r8, r0, 0, 4
    add   r6, r6, 4
    sbbo  &r6, r4, 4, 4
    wbc   r31.t0                 ; falling edge -> left mics
    and   r30.b0, r8.b0, 0x0F
    wbs   r31.t0                 ; rising edge -> right mics
    lsr   r30.b0, r8.b0, 4
    wbc   r31.t0                 ; falling edge -> left mics
    and   r30.b0, r8.b1, 0x0F
    wbs   r31.t0                 ; rising edge -> right mics
    lsr   r30.b0, r8.b1, 4
    wbc   r31.t0                 ; falling edge -> left mics
    and   r30.b0, r8.b2, 0x0F
    wbs   r31.t0                 ; rising edge -> right mics
    lsr   r30.b0, r8.b2, 4
    wbc   r31.t0                 ; falling edge -> left mics
    and   r30.b0, r8.b3, 0x0F
    wbs   r31.t0                 ; rising edge -> right mics
    lsr   r30.b0, r8.b3, 4
    qba   fetch
done:
    ldi   r0, 1
    sbbo  &r0, r4, 12, 4
    halt
underrun:
    ldi   r0, 2
    sbbo  &r0, r4, 12, 4
    halt
