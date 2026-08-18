# Сборка headless-драйвера эталона rffit.
#
# PGPLOT, GSL, X11 и libpng не нужны: ни один символ cpg* не вызывается
# (все они внутри main() в rffit.c, а он отключён), а gsl в исходниках strf
# не используется вообще — только в LFLAGS их makefile. Достаточно -lm.
#
# rfsites.c не линкуется: сломан в форке, свой get_site лежит в driver.c.
# rftime.c не линкуется: его date2mjd/nfd2mjd/mjd2nfd дублируют копии,
# которые приходят вместе с rffit.c.

STRF ?= ../../../../strf

CC     = gcc
CFLAGS = -O3 -fcommon -I. -I$(STRF)
OBJS   = $(STRF)/sgdp4.c $(STRF)/deep.c $(STRF)/ferror.c $(STRF)/satutl.c \
         $(STRF)/dsmin.c $(STRF)/simplex.c $(STRF)/versafit.c $(STRF)/rftles.c

driver: driver.c cpgstub.c cpgplot.h
	$(CC) $(CFLAGS) -o $@ driver.c cpgstub.c $(OBJS) -lm

# Пересоздание эталонов. Запускается вручную и осознанно: golden-файлы
# коммитятся, и обновлять их ради зелёного CI нельзя (правило 5).
# В CI компилятор C не нужен — там сравнение идёт с закоммиченным JSON.
#
# Пары данных и элементов подобраны по совпадению эпохи с интервалом данных;
# объект 61782 для tusur338obs.dat найден скринингом по всему TLE-2024199.dat
# (0.543 кГц против 0.671 у следующего кандидата).
GOLDEN = ../golden
DATA   = $(STRF)

golden: driver
	ST_DATADIR=$(STRF) ./driver $(DATA)/tab_lobach_1.dat $(DATA)/lobach.tle \
		98423 1111111 $(GOLDEN)/lobach_all_free.json
	ST_DATADIR=$(STRF) ./driver $(DATA)/tab_lobach_1.dat $(DATA)/lobach.tle \
		98423 0101010 $(GOLDEN)/lobach_raan_argp_n.json
	# Первый шаг гайда: сдвиг всех точек на частоту спутника **только**
	# аргументом перигея (клавиша 4). Одна свободная величина — самый жёсткий
	# случай для маски: любая протечка соседнего параметра тут же видна.
	ST_DATADIR=$(STRF) ./driver $(DATA)/tab_lobach_1.dat $(DATA)/lobach.tle \
		98423 0001000 $(GOLDEN)/lobach_argp_only.json
	ST_DATADIR=$(STRF) ./driver $(DATA)/tusur338obs.dat $(DATA)/TLE-2024199.dat \
		61782 1111111 $(GOLDEN)/tusur338_all_free.json

clean:
	rm -f driver

.PHONY: clean golden
