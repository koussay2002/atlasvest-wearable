// alert_logic.h — logique d'alerte pure (aucune dépendance Arduino) => testable sur PC.
// Reprend les niveaux du diagramme d'états du rapport : OK / ORANGE / ROUGE.
#pragma once
#include <math.h>

enum Level { LEVEL_OK = 0, LEVEL_ORANGE = 1, LEVEL_RED = 2 };

struct Thresholds {
  float hr_orange = 140.0f;  // bpm : seuil imposé par le sujet (configurable par MQTT)
  float hr_red    = 180.0f;  // bpm
  float t_orange  = 38.0f;   // °C : température anormale (simulée par le DHT22)
  float t_red     = 39.5f;   // °C : contrainte thermique sévère
  float t_low     = 34.0f;   // °C : sous ce seuil = capteur décroché / hypothermie
  float hr_hyst   = 5.0f;    // bpm : hystérésis de retour
  float t_hyst    = 0.3f;    // °C  : hystérésis de retour
  int   confirm   = 3;       // nb de mesures consécutives pour changer de niveau
};

struct AlertEngine {
  Thresholds th;
  Level level = LEVEL_OK;
  Level pendLevel = LEVEL_OK;
  int   pend = 0;

  // Niveau "instantané" demandé par les mesures, avec hystérésis selon le niveau courant.
  Level target(float hr, float temp, bool tempOk) const {
    const bool inAlert = level >= LEVEL_ORANGE, inRed = level >= LEVEL_RED;
    const float hrO = th.hr_orange - (inAlert ? th.hr_hyst : 0.0f);
    const float hrR = th.hr_red    - (inRed   ? th.hr_hyst : 0.0f);
    const float tO  = th.t_orange  - (inAlert ? th.t_hyst  : 0.0f);
    const float tR  = th.t_red     - (inRed   ? th.t_hyst  : 0.0f);
    const float tL  = th.t_low     + (inAlert ? th.t_hyst  : 0.0f);
    const bool red = (hr >= hrR) || (tempOk && temp >= tR);
    // Capteur de température défaillant => ORANGE par sécurité (jamais "normal" par défaut)
    const bool orange = (hr > hrO) || !tempOk || (tempOk && (temp >= tO || temp < tL));
    return red ? LEVEL_RED : (orange ? LEVEL_ORANGE : LEVEL_OK);
  }

  // Appel à chaque mesure ; renvoie le niveau (changement seulement après 'confirm' mesures).
  Level update(float hr, float temp, bool tempOk) {
    const Level c = target(hr, temp, tempOk);
    if (c == level) { pend = 0; pendLevel = level; return level; }
    if (c == pendLevel) pend++; else { pendLevel = c; pend = 1; }
    if (pend >= th.confirm) { level = c; pend = 0; }
    return level;
  }
};

inline const char* levelName(Level l) { return l == LEVEL_RED ? "ROUGE" : (l == LEVEL_ORANGE ? "ORANGE" : "OK"); }
