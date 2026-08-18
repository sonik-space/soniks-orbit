/* Headless-драйвер эталона rffit.
 *
 *   ./driver <файл.dat> <файл.tle> <номер> <маска> <выход.json>
 *
 * Пишет JSON с тем, что нужно лестнице тестов из testing.md §1:
 * лучевую скорость на каждой точке при затравке (ступень 1), несущую
 * и RMS до фита (ступень 2), элементы, несущую и RMS после фита (ступень 3),
 * азимут, высоту и момент наибольшего сближения (ступень 5).
 *
 * Маска — семь символов 0/1 в порядке параметров rffit
 * (incl, RAAN, ecc, argp, M, rev/day, B*): какие параметры свободны.
 * Записывается в JSON, потому что golden без неё невоспроизводим.
 *
 * JSON идёт в файл, а не в stdout: load_tles печатает "Loaded N orbits",
 * а sgdp4.c — предупреждения о суборбитальных решениях, оба через printf.
 * Смешать их с JSON значит сделать golden неразбираемым.
 *
 * Математика берётся из rffit.c включением исходника целиком, а не
 * копированием функций: скопированная математика расходится с эталоном
 * молча, и отличить ошибку копирования от ошибки порта потом невозможно.
 * main() в rffit.c переименовывается, чтобы не конфликтовать с нашим.
 */
#define main rffit_main_unused
#include "rffit.c"
#undef main

/* rfsites.c не линкуется: в форке он сломан (правило 4 в
 * ai-development-rules.md) — sprintf на строке 34 затирает вычисленный путь
 * захардкоженным "/home/user/strf/data/sites.txt", плюс printf(filename)
 * с пользовательской строкой в качестве формата. Здесь та же логика без
 * этих двух дефектов. */
site_t get_site(int site_id)
{
  char line[LIM], filename[LIM];
  char *env_datadir, *env_sites_txt;
  FILE *file;
  int id, count = 0;
  double lat, lng;
  float alt;
  char abbrev[3];
  site_t s;

  env_sites_txt = getenv("ST_SITES_TXT");
  if (env_sites_txt != NULL && strlen(env_sites_txt) > 0) {
    snprintf(filename, sizeof(filename), "%s", env_sites_txt);
  } else {
    env_datadir = getenv("ST_DATADIR");
    if (env_datadir == NULL || strlen(env_datadir) == 0)
      env_datadir = ".";
    snprintf(filename, sizeof(filename), "%s/data/sites.txt", env_datadir);
  }

  file = fopen(filename, "r");
  if (file == NULL) {
    fprintf(stderr, "driver: не открывается %s\n", filename);
    exit(1);
  }
  while (fgets(line, LIM, file) != NULL) {
    if (strstr(line, "#") != NULL)
      continue;
    if (sscanf(line, "%4d %2s %lf %lf %f", &id, abbrev, &lat, &lng, &alt) != 5)
      continue;
    if (id == site_id) {
      s.id = id;
      s.lat = lat;
      s.lng = lng;
      s.alt = alt / 1000.0;   /* sites.txt в метрах, strf работает в км */
      snprintf(s.observer, sizeof(s.observer), "%s", line + 38);
      count++;
    }
  }
  fclose(file);

  if (count == 0) {
    fprintf(stderr, "driver: станция %d не найдена в %s\n", site_id, filename);
    exit(1);
  }
  return s;
}

/* Элементы -> вектор параметров rffit (см. комментарий в chisq). */
static void orb2a(orbit_t o, double a[7])
{
  a[0] = DEG(o.eqinc);
  a[1] = DEG(o.ascn);
  a[2] = o.ecc;
  a[3] = DEG(o.argp);
  a[4] = DEG(o.mnan);
  a[5] = o.rev;
  a[6] = o.bstar;
}

static void print_elements(FILE *fp, const char *key, orbit_t o)
{
  fprintf(fp, "\"%s\":{\"incl_deg\":%.12f,\"raan_deg\":%.12f,\"ecc\":%.12f,"
          "\"argp_deg\":%.12f,\"ma_deg\":%.12f,\"rev_per_day\":%.12f,"
          "\"bstar\":%.12e,\"epoch_mjd\":%.12f}",
          key, DEG(o.eqinc), DEG(o.ascn), o.ecc, DEG(o.argp), DEG(o.mnan),
          o.rev, o.bstar, date2mjd(o.ep_year, 1, o.ep_day));
}

int main(int argc, char *argv[])
{
  int i, j, k, ntca, satno, imode;
  int ia[7];
  double a[7], *vseed, *aziseed, *altseed, *tca, azi, alt;
  double mjd, v, vtca, mjdtca, gmin, gmax;
  int *tca_site;
  double rms_pre, ffit_pre, rms_post;
  orbit_t seed;
  tle_array_t *tle_array;
  tle_t *tle;
  FILE *out;

  if (argc != 6) {
    fprintf(stderr, "usage: %s <file.dat> <file.tle> <satno> <mask7> <out.json>\n",
            argv[0]);
    return 1;
  }
  satno = atoi(argv[3]);

  if (strlen(argv[4]) != 7) {
    fprintf(stderr, "driver: маска должна быть из семи символов 0/1\n");
    return 1;
  }
  for (i = 0; i < 7; i++)
    ia[i] = (argv[4][i] == '1') ? 1 : 0;

  /* Данные. Все точки помечаются как выбранные — headless-эквивалент
   * клавиши 's' (highlight) в интерактивном rffit. */
  d = read_data(argv[1], 0, 0.0);
  for (i = 0; i < d.n; i++)
    d.p[i].flag = 2;
  d.fitfreq = 1;                         /* несущая решается аналитически */

  /* Затравка. Присваивание в ГЛОБАЛЬНУЮ orb обязательно: fit_curve
   * принимает орбиту по значению, параметр затеняет глобаль, и её
   * финальные присваивания уходят в мёртвую копию. Результат доходит
   * только через глобальную orb, которую пишет chisq (rffit.c:166-168). */
  tle_array = load_tles(argv[2]);
  if (tle_array == NULL || tle_array->number_of_elements == 0) {
    fprintf(stderr, "driver: нет элементов в %s\n", argv[2]);
    return 1;
  }
  tle = get_tle_by_catalog_id(tle_array, satno);
  if (tle == NULL) {
    fprintf(stderr, "driver: объект %d не найден в %s\n", satno, argv[2]);
    return 1;
  }
  orb = tle->orbit;
  d.satname = tle->name;
  imode = init_sgdp4(&orb);
  if (imode == SGDP4_ERROR) {
    fprintf(stderr, "driver: init_sgdp4 не смог %d\n", orb.satno);
    return 1;
  }
  seed = orb;

  /* Ступень 1: лучевая скорость на каждой точке при затравке.
   * Азимут и высоту velocity() считает той же прогонкой (ступень 5). */
  vseed = (double *) malloc(sizeof(double) * d.n);
  aziseed = (double *) malloc(sizeof(double) * d.n);
  altseed = (double *) malloc(sizeof(double) * d.n);
  for (i = 0; i < d.n; i++)
    velocity(seed, d.p[i].mjd, d.p[i].s, &vseed[i], &aziseed[i], &altseed[i]);

  /* Ступень 5: момент наибольшего сближения. Сетка и условие — из цикла
   * отрисовки rffit.c:496-506: 1024 отсчёта по интервалу данных, расширенному
   * на 10% в обе стороны, смена знака лучевой скорости над горизонтом,
   * последняя из найденных.
   *
   * Считается ЗДЕСЬ, а не при выводе, хотя выводится вместе с ним. velocity()
   * принимает orbit_t, но не использует его: положение спутника даёт
   * satpos_xyz из ГЛОБАЛЬНОГО состояния, инициализированного init_sgdp4.
   * После fit_curve это состояние — уже подогнанные элементы, и тот же цикл
   * ниже по тексту молча посчитал бы TCA не по той орбите, что столбцы
   * azi/alt рядом. Расхождение видно: на site 43 оно составило 94 минуты.
   *
   * Отличий от rffit два, оба намеренные.
   *
   * Первое: rffit считает TCA для ОДНОЙ станции (та, что в ST_COSPAR), потому
   * что рисует одну панель неба. Здесь — на каждую станцию набора: их до пяти,
   * и низкий проход, где кривая пересекает нуль полого, — самый неудобный
   * случай для сравнения интерполяции с «ближайшим из 1024».
   *
   * Второе: сетка идёт в double, а у rffit xmin/xmax — float (наследство осей
   * PGPLOT). Разница по времени ~3 мс при шаге сетки ~26 с, то есть на четыре
   * порядка ниже допуска теста, зато сетка воспроизводима по границам, которые
   * печатаются рядом. Без них «один шаг отсчёта» в тесте — число из воздуха. */
  gmin = d.mjdmin - 0.1 * d.dmjd;
  gmax = d.mjdmax + 0.1 * d.dmjd;
  tca_site = (int *) malloc(sizeof(int) * d.n);
  tca = (double *) malloc(sizeof(double) * d.n);
  for (i = 0, ntca = 0; i < d.n; i++) {
    for (j = 0; j < i; j++)
      if (d.p[j].site_id == d.p[i].site_id)
        break;
    if (j < i)
      continue;

    mjdtca = -1.0;
    vtca = 0.0;
    for (k = 0; k < NMAX; k++) {
      mjd = gmin + (gmax - gmin) * (double) k / (double) (NMAX - 1);
      velocity(seed, mjd, d.p[i].s, &v, &azi, &alt);
      if (k > 0 && vtca * v < 0.0 && alt > 0.0 && mjd < d.mjdmax && mjd > d.mjdmin)
        mjdtca = mjd;
      vtca = v;
    }
    tca_site[ntca] = d.p[i].site_id;
    tca[ntca++] = mjdtca;
  }

  /* Ступень 2: несущая и RMS до фита. chisq пишет d.ffit и глобальную orb,
   * compute_rms читает их же. */
  orb2a(seed, a);
  chisq(a);
  ffit_pre = d.ffit;
  rms_pre = compute_rms();

  /* Ступень 3: фит. */
  orb = seed;
  init_sgdp4(&orb);
  rms_post = fit_curve(orb, ia);

  /* Вывод. Частоты в кГц — как внутри rffit (decode_line делает freq*=1e-3),
   * поэтому суффикс _khz в именах. */
  out = fopen(argv[5], "w");
  if (out == NULL) {
    fprintf(stderr, "driver: не пишется %s\n", argv[5]);
    return 1;
  }
  fprintf(out, "{\"dat\":\"%s\",\"tle\":\"%s\",\"satno\":%d,\"n_points\":%d,\n",
          argv[1], argv[2], satno, d.n);
  fprintf(out, " \"free_params\":\"%s\",\n", argv[4]);
  fprintf(out, " ");
  print_elements(out, "seed", seed);
  fprintf(out, ",\n \"points\":[\n");
  for (i = 0; i < d.n; i++) {
    fprintf(out,
            "  {\"mjd\":%.12f,\"freq_khz\":%.9f,\"flux\":%.6f,\"site_id\":%d,"
            "\"lat_deg\":%.6f,\"lng_deg\":%.6f,\"alt_km\":%.6f,\"v_km_s\":%.15e,"
            "\"azi_deg\":%.12f,\"alt_deg\":%.12f}%s\n",
            d.p[i].mjd, d.p[i].freq, d.p[i].flux, d.p[i].site_id,
            d.p[i].s.lat, d.p[i].s.lng, (double) d.p[i].s.alt, vseed[i],
            aziseed[i], altseed[i],
            (i == d.n - 1) ? "" : ",");
  }
  fprintf(out, " ],\n");

  fprintf(out, " \"grid\":{\"mjd_min\":%.12f,\"mjd_max\":%.12f,\"n\":%d},\n",
          gmin, gmax, NMAX);
  fprintf(out, " \"tca\":[\n");
  for (i = 0; i < ntca; i++) {
    fprintf(out, "  {\"site_id\":%d,", tca_site[i]);
    if (tca[i] < 0.0)
      fprintf(out, "\"mjd\":null}");
    else
      fprintf(out, "\"mjd\":%.12f}", tca[i]);
    fprintf(out, "%s\n", (i == ntca - 1) ? "" : ",");
  }
  fprintf(out, " ],\n");
  fprintf(out, " \"pre\":{\"ffit_khz\":%.12f,\"rms_khz\":%.12f},\n", ffit_pre, rms_pre);
  fprintf(out, " \"post\":{\"ffit_khz\":%.12f,\"rms_khz\":%.12f,", d.ffit, rms_post);
  print_elements(out, "elements", orb);
  fprintf(out, "}\n}\n");
  fclose(out);

  free(vseed);
  free(aziseed);
  free(altseed);
  free(tca_site);
  free(tca);
  free_tles(tle_array);
  return 0;
}
