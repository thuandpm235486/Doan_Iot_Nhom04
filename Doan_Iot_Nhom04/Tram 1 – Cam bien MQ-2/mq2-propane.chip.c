// Educational model, not calibrated hardware. See gas_model.py and model documentation.
// Approximate Fig.5 of Winsen MQ-2 v1.5: propane, Vc=5V, RL=4.7k.
#include "wokwi-api.h"
#include <math.h>
#include <stdlib.h>
#include <stdbool.h>

static const float CURVE_PPM[] = {300,500,1000,2000,3000,4000,5000,6000,7000,10000};
static const float CURVE_V[] = {1.70,2.50,3.10,3.55,3.85,4.10,4.22,4.30,4.42,4.46};
typedef struct {
  pin_t vcc, gnd, aout, ready, health;
  uint32_t ppm_attr, fault_attr, warmup_attr;
  uint64_t started_ns;
  bool previously_powered;
} chip_state_t;

static float sensor_voltage(float ppm) {
  if (ppm < 300) ppm = 300;
  if (ppm > 10000) ppm = 10000;
  for (unsigned i=0; i<9; ++i) {
    if (ppm <= CURVE_PPM[i+1]) {
      const float r1 = 4700.0f*(5.0f/CURVE_V[i]-1.0f);
      const float r2 = 4700.0f*(5.0f/CURVE_V[i+1]-1.0f);
      const float t = logf(ppm/CURVE_PPM[i])/logf(CURVE_PPM[i+1]/CURVE_PPM[i]);
      const float rs = expf(logf(r1)+t*logf(r2/r1));
      return 5.0f*4700.0f/(rs+4700.0f);
    }
  }
  return CURVE_V[9];
}

static void update_chip(void *user_data) {
  chip_state_t *s = (chip_state_t *)user_data;
  float supply = pin_adc_read(s->vcc) - pin_adc_read(s->gnd);
  bool powered = isfinite(supply) && supply >= 4.9f && supply <= 5.1f;
  uint64_t now = get_sim_nanos();
  unsigned fault = attr_read(s->fault_attr);
  bool heater_powered = powered && fault != 1;
  if (heater_powered && !s->previously_powered) s->started_ns = now;
  s->previously_powered = heater_powered;
  float ppm = attr_read_float(s->ppm_attr);
  bool healthy = powered && fault == 0 && isfinite(ppm);
  uint64_t warmup_ns = (uint64_t)attr_read(s->warmup_attr)*1000000000ULL;
  bool ready = healthy && now - s->started_ns >= warmup_ns;
  float output = healthy ? 0.4f*sensor_voltage(ppm) : 0.0f;
  if (powered && fault == 3) output = 2.0f;
  // Output conditioner represents ideal buffer + 15k/10k divider, max 2V.
  pin_dac_write(s->aout, output);
  pin_write(s->health, healthy ? HIGH : LOW);
  pin_write(s->ready, ready ? HIGH : LOW);
}

void chip_init(void) {
  chip_state_t *s = calloc(1, sizeof(chip_state_t));
  s->vcc = pin_init("VCC", ANALOG);
  s->gnd = pin_init("GND", ANALOG);
  s->aout = pin_init("AOUT", ANALOG);
  s->ready = pin_init("READY", OUTPUT_LOW);
  s->health = pin_init("HEALTH", OUTPUT_LOW);
  s->ppm_attr = attr_init_float("gasPpm", 400.0f);
  s->fault_attr = attr_init("faultMode", 0);
  s->warmup_attr = attr_init("warmupSeconds", 5);
  s->started_ns = get_sim_nanos();
  const timer_config_t timer = {.callback=update_chip,.user_data=s};
  timer_t handle = timer_init(&timer);
  timer_start(handle, 100000, true);
  update_chip(s);
}
