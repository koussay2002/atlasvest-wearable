// Test sur PC de la logique d'alerte (même fichier alert_logic.h que le firmware ESP32).
// Compilation : g++ -std=c++17 -I sim/wokwi tests/test_alert_logic.cpp -o tests/test_alert && ./tests/test_alert
#include <cstdio>
#include <cstring>
#include "alert_logic.h"

static int total = 0, passed = 0;
static FILE* trace = nullptr;
static int step = 0;

static void check(const char* name, Level got, Level want) {
  ++total; const bool ok = (got == want); passed += ok;
  std::printf("[%s] %-62s attendu=%-6s obtenu=%-6s\n", ok ? "OK " : "ERR", name, levelName(want), levelName(got));
}
// Envoie n mesures identiques ; renvoie le niveau final.
static Level feed(AlertEngine& e, float hr, float t, bool ok, int n) {
  for (int i = 0; i < n; ++i) { e.update(hr, t, ok); if (trace) std::fprintf(trace, "%d,%.1f,%.1f,%d,%d,%s\n", ++step, hr, t, ok, (int)e.level, levelName(e.level)); }
  return e.level;
}

int main() {
  trace = std::fopen("data/scenario_trace.csv", "w");
  if (trace) std::fprintf(trace, "step,hr_bpm,temp_c,sensor_ok,level,state\n");
  AlertEngine e;
  check("repos : 80 bpm / 36,8 C x10 -> reste OK",               feed(e, 80, 36.8f, true, 10), LEVEL_OK);
  check("pic isole : 1 mesure a 150 bpm puis retour 80 -> OK",   (feed(e, 150, 36.8f, true, 1), feed(e, 80, 36.8f, true, 3)), LEVEL_OK);
  check("150 bpm x2 -> pas encore d'alerte (confirmation = 3)",  feed(e, 150, 36.8f, true, 2), LEVEL_OK);
  check("150 bpm x3 -> ORANGE (seuil sujet 140 bpm)",            feed(e, 150, 36.8f, true, 1), LEVEL_ORANGE);
  check("185 bpm x3 -> ROUGE",                                   feed(e, 185, 36.8f, true, 3), LEVEL_RED);
  check("138 bpm x3 : hysteresis -> descend a ORANGE (> 135)",   feed(e, 138, 36.8f, true, 3), LEVEL_ORANGE);
  check("138 bpm x3 de plus -> reste ORANGE (hysteresis)",       feed(e, 138, 36.8f, true, 3), LEVEL_ORANGE);
  check("130 bpm x3 -> retour OK",                               feed(e, 130, 36.8f, true, 3), LEVEL_OK);
  check("38,2 C x3 -> ORANGE (temperature anormale)",            feed(e, 90, 38.2f, true, 3), LEVEL_ORANGE);
  check("39,6 C x3 -> ROUGE",                                    feed(e, 90, 39.6f, true, 3), LEVEL_RED);
  check("37,0 C x3 -> retour OK apres ROUGE puis ORANGE",        (feed(e, 90, 37.0f, true, 3), feed(e, 90, 37.0f, true, 3)), LEVEL_OK);
  check("DHT22 en defaut x3 -> ORANGE (jamais 'normal' par defaut)", feed(e, 90, 36.8f, false, 3), LEVEL_ORANGE);
  check("capteur retabli x3 -> OK",                              feed(e, 90, 36.8f, true, 3), LEVEL_OK);
  check("33,0 C x3 (capteur decroche / hypothermie) -> ORANGE",  feed(e, 90, 33.0f, true, 3), LEVEL_ORANGE);
  AlertEngine p; p.th.hr_orange = 160;                             // seuil personnalise (commande MQTT hr_max=160)
  check("seuil personnalise 160 : 150 bpm x5 -> OK",             feed(p, 150, 36.8f, true, 5), LEVEL_OK);
  check("seuil personnalise 160 : 170 bpm x3 -> ORANGE",         feed(p, 170, 36.8f, true, 3), LEVEL_ORANGE);
  std::printf("\nResultat : %d/%d tests reussis\n", passed, total);
  if (trace) std::fclose(trace);
  return passed == total ? 0 : 1;
}
