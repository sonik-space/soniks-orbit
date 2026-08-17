/* Заглушка PGPLOT.
 *
 * rffit.c делает #include <cpgplot.h> и вызывает 20 функций cpg*, но все
 * вызовы находятся внутри main(), который в драйвере отключён. Настоящий
 * PGPLOT не нужен ни при сборке, ни при запуске (testing.md §1).
 *
 * Параметры намеренно не специфицированы: заглушке всё равно, с чем её
 * вызывают, а объявить точные сигнатуры двадцати функций — это тащить
 * настоящий заголовок.
 */
#ifndef _CPGPLOT_STUB_H
#define _CPGPLOT_STUB_H

int cpgask();
int cpgband();
int cpgbox();
int cpgcirc();
int cpgclos();
int cpgdraw();
int cpgenv();
int cpglab();
int cpgmove();
int cpgmtxt();
int cpgopen();
int cpgpage();
int cpgpt1();
int cpgsci();
int cpgsfs();
int cpgsls();
int cpgsvp();
int cpgswin();
int cpgtext();
int cpgwnad();

#endif /* _CPGPLOT_STUB_H */
