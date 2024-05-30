# Caravel with Z80 to DIP40 adapter PCB

See: https://github.com/rejunity/z80-open-silicon

## Pinout

                                   Z80 CPU
                   ,----------------.___.----------------.
      <--    A11  1| io[19] 57                 55 io[18] |40 A10    -->
      <--    A12  2| io[20] 58                 54 io[17] |39 A9     -->
      <--    A13  3| io[21] 59                 53 io[16] |38 A8     -->
      <--    A14  4| io[22] 60                 51 io[15] |37 A7     -->
      <--    A15  5| io[23] 61                 50 io[14] |36 A6     -->
      -->    CLK  6|  XCLK  22                 48 io[13] |35 A5     -->
      <->     D4  7| io[24] 62                 42 io[8]  |34 A4     -->
      <->     D3  8| io[25]  2                 43 io[9]  |33 A3     -->
      <->     D5  9| io[26]  3                 44 io[10] |32 A2     -->
      <->     D6 10| io[27]  4                 46 io[12] |31 A1     -->
         VCC_5V0 11|               Caravel     45 io[11] |30 A0     -->
      <->     D2 12| io[28]  5       pins                |29 GND
      <->     D7 13| io[29]  6                 41 io[7]  |28 /RFSH  -->
      <->     D0 14| io[31]  8                 33 io[2]  |27 /M1    -->
      <->     D1 15| io[30]  7                 21  RST   |26 /RESET <--
      -->   /INT 16| io[33] 12                 34 io[3]  |25 /BUSRQ <--
      -->   /NMI 17| io[32] 11                 37 io[6]  |24 /WAIT  <--
      <--  /HALT 18| io[0]  31                 32 io[1]  |23 /BUSAK -->
      <--  /MREQ 19| io[34] 13                 36 io[5]  |22 /WR    -->
      <--  /IORQ 20| io[35] 14                 35 io[4]  |21 /RD    -->
                   `-------------------------------------'


## Power rails for Caravel
        GND     29 (Z80) --- vss*               56, 52, 38, 39, 29, 23, 20, 10, 1
        VCC_5V0 11 (Z80) --- vddio              64, 17
        VCC_1V8    (LDO) --- vccd, vccd1, vccd2 63, 49, 18
