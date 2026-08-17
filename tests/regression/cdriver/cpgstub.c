/* Тела заглушек PGPLOT. Ни одна не вызывается: все вызовы cpg* в rffit.c
 * лежат внутри main(), который драйвер переименовывает и не запускает. */
#include "cpgplot.h"

int cpgask()  { return 0; }
int cpgband() { return 0; }
int cpgbox()  { return 0; }
int cpgcirc() { return 0; }
int cpgclos() { return 0; }
int cpgdraw() { return 0; }
int cpgenv()  { return 0; }
int cpglab()  { return 0; }
int cpgmove() { return 0; }
int cpgmtxt() { return 0; }
int cpgopen() { return 1; }
int cpgpage() { return 0; }
int cpgpt1()  { return 0; }
int cpgsci()  { return 0; }
int cpgsfs()  { return 0; }
int cpgsls()  { return 0; }
int cpgsvp()  { return 0; }
int cpgswin() { return 0; }
int cpgtext() { return 0; }
int cpgwnad() { return 0; }
