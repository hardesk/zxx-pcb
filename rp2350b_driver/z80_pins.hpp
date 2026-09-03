#pragma once

#include <cstdint>

enum Pins : unsigned {
    pD0  =  0,
    pD1  =  1,
    pD2  =  2,
    pD3  =  3,
    pD4  =  4,
    pD5  =  5,
    pD6  =  6,
    pD7  =  7,

    pA0  =  8,
    pA1  =  9,
    pA2  = 10,
    pA3  = 11,
    pA4  = 12,
    pA5  = 13,
    pA6  = 14,
    pA7  = 15,
    pA8  = 16,
    pA9  = 17,
    pA10 = 18,
    pA11 = 19,
    pA12 = 20,
    pA13 = 21,
    pA14 = 22,
    pA15 = 23,

    pCLK   = 24, // Z80 input
    pRESET = 25, // Z80 input
    pWAIT  = 26, // Z80 input
    pM1    = 27, // Z80 output
    pMREQ  = 28, // Z80 output
    pIORQ  = 29, // Z80 output
    pRD    = 30, // Z80 output
    pWR    = 31, // Z80 output

    pINT    = 32, // Z80 input
    pNMI    = 33, // Z80 input
    pBUSRQ  = 34, // Z80 input
    pBUSACK = 35, // Z80 output
    pHALT   = 36, // Z80 output

    pPIN_COUNT
};

constexpr uint32_t kZ80DataMask = 0x0000'00ffu;
constexpr uint32_t kZ80AddressMask = 0x00ff'ff00u;
