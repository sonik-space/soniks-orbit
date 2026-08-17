/* Headless-драйвер эталона rffit.
 *
 *   ./driver <файл.dat> <файл.tle> <номер> <маска> <выход.json>
 *
 * Пишет JSON с тем, что нужно лестнице тестов из testing.md §1:
 * лучевую скорость на каждой точке при затравке (ступень 1), несущую
 * и RMS до фита (ступень 2), элементы, несущую и RMS после фита (ступень 3).
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
  int i, satno, imode;
  int ia[7];
  double a[7], *vseed, azi, alt;
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

  /* Ступень 1: лучевая скорость на каждой точке при затравке. */
  vseed = (double *) malloc(sizeof(double) * d.n);
  for (i = 0; i < d.n; i++)
    velocity(seed, d.p[i].mjd, d.p[i].s, &vseed[i], &azi, &alt);

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
            "\"lat_deg\":%.6f,\"lng_deg\":%.6f,\"alt_km\":%.6f,\"v_km_s\":%.15e}%s\n",
            d.p[i].mjd, d.p[i].freq, d.p[i].flux, d.p[i].site_id,
            d.p[i].s.lat, d.p[i].s.lng, (double) d.p[i].s.alt, vseed[i],
            (i == d.n - 1) ? "" : ",");
  }
  fprintf(out, " ],\n");
  fprintf(out, " \"pre\":{\"ffit_khz\":%.12f,\"rms_khz\":%.12f},\n", ffit_pre, rms_pre);
  fprintf(out, " \"post\":{\"ffit_khz\":%.12f,\"rms_khz\":%.12f,", d.ffit, rms_post);
  print_elements(out, "elements", orb);
  fprintf(out, "}\n}\n");
  fclose(out);

  free(vseed);
  free_tles(tle_array);
  return 0;
}
