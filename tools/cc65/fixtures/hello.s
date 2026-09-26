; Minimal 6502 program for ca65/ld65 round-trip (spec §6.3).
        .setcpu "6502"

        .export __START__ : absolute

__START__:
        rts
