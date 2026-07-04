# ha-energy-planner

[English](README.md) | Česky

Vlastní integrace pro Home Assistant pro plánování FVE, baterie, tarifů a EV.

> [!WARNING]
> Energy Planner je experimentální software v aktivním vývoji. Není doporučen pro produkční použití. Instalaci a používání provádíte na vlastní riziko. Nespoléhejte na něj pro bezpečnostně kritická, životně důležitá, majetkově ochranná, nouzová, provozní, finanční, fakturační, regulatorní ani compliance rozhodnutí.

Integrace pouze počítá výstupy energetického plánování. Ve verzi v1 **neovládá**
Victron, EV nabíječky, topení ani jiná zařízení. Pokud její senzory použijete v
automatizacích, odpovídáte za ověření chování automatizace a za všechny důsledky
těchto automatizací.

## Instalace

Vlastní repozitář v HACS:

1. Přidejte `https://github.com/ara686/ha-energy-planner` jako vlastní repozitář typu Integration.
2. Nainstalujte Energy Planner přes HACS.
3. Restartujte Home Assistant.
4. Přidejte integraci v Settings > Devices & services.

Ruční instalace:

1. Zkopírujte `custom_components/energy_planner` do adresáře `custom_components` ve vašem Home Assistantu.
2. Restartujte Home Assistant.
3. Přidejte integraci z UI.

YAML konfigurace není ve verzi v1 záměrně podporovaná.

## Konfigurace

Energy Planner se konfiguruje pouze přes UI Home Assistantu. Očekává už
existující entity v Home Assistantu; ve verzi v1 za vás nevytváří pomocné
senzory.

### Vstupní entity

Tyto hodnoty se vybírají v setup UI. Sloupec `Key` je uložený konfigurační klíč
používaný v diagnostice a debug výstupech.

| Položka v setupu | Key | Povinné | Očekávaný vstup | Poznámky a příklady |
|------------------|-----|---------|-----------------|---------------------|
| Stav nabití baterie | `battery_soc_entity` | Povinné | Číselný senzor SoC baterie v `%`. | Použijte SoC entitu z integrace FVE/bateriového měniče, například Victron, GoodWe, Solax, Huawei nebo SolarEdge. |
| Kapacita baterie | `battery_capacity_entity` | Povinné | Číselný senzor kapacity baterie v `kWh`. | Použijte entitu z měniče/BMS, pokud existuje. Pokud je kapacita fixní a měnič ji neposkytuje, vytvořte v Home Assistantu helper s nastavenou hodnotou kapacity. |
| Minimální stav nabití baterie | `battery_min_soc_entity` | Povinné | Číselný senzor minimálního/rezervního SoC v `%`. | Použijte entitu minimálního SoC z měniče/BMS. Pokud systém má jen fixní rezervu, vytvořte pro ni helper. |
| Historie hodinové spotřeby domu | `home_energy_hourly_entity` | Povinné | Hodinový `utility_meter` senzor v `kWh`. | Vytvořte Utility Meter helper s cyklem `hourly` ze senzoru celkové spotřeby domu. Toto je hlavní historický vstup spotřeby domu. |
| Historie hodinové řízené spotřeby | `managed_energy_hourly_entity` | Volitelné | Hodinový `utility_meter` senzor v `kWh`. | Vytvořte další hodinový Utility Meter ze záměrně řízené spotřeby, například nabíjení EV, bojleru nebo ohřevu vody. Tato hodnota se odečítá od spotřeby domu po hodinách. |
| Solcast predikce pro dnešek | `solcast_today_entity` | Volitelné | Solcast forecast senzor z Home Assistantu. | Příklad: `sensor.solcast_pv_forecast_forecast_today`. Energy Planner čte pouze data z Home Assistantu a nevolá Solcast přímo. |
| Solcast predikce pro zítřek | `solcast_tomorrow_entity` | Volitelné | Solcast forecast senzor z Home Assistantu. | Příklad: `sensor.solcast_pv_forecast_forecast_tomorrow`. Pokud entita pro dnešek používá standardní Solcast naming pattern, Energy Planner umí tuto sourozeneckou entitu najít automaticky. |
| Další dny Solcast predikce | `solcast_additional_entities` | Volitelné | Jedna nebo více Solcast forecast entit z Home Assistantu. | Příklady: `sensor.solcast_pv_forecast_forecast_day_3`, `sensor.solcast_pv_forecast_forecast_day_4`. Standardní sourozenci `forecast_day_3` až `forecast_day_7` mohou být automaticky nalezeni, pokud existují. |
| Cena nebo tarif | `price_entity` | Volitelné | Číselný senzor ceny/tarifu nebo stavová entita tarifu. | Rezervováno pro plánování a diagnostiku podle tarifů. Aktuální v1 planner z tohoto vstupu neovládá zařízení. |

### Příprava hodinových helperů spotřeby

Energy Planner potřebuje hodinové energetické součty, ne okamžité hodnoty výkonu.
Pro vstupy historie domu a řízené spotřeby vytvořte v Home Assistantu Utility
Meter helpery:

1. Přejděte do Settings > Devices & services > Helpers.
2. Create helper > Utility Meter.
3. Vyberte zdrojový energetický senzor v `kWh`.
4. Nastavte reset cycle na `hourly`.
5. Tarify nechte prázdné, pokud výslovně nepotřebujete oddělené tarifní měřáky.
6. Helper uložte a vytvořený senzor použijte jako vstup Energy Planneru.

Pro `Home hourly consumption history` má zdroj reprezentovat celkovou spotřebu
domu. Dobré zdroje jsou podle dostupných dat z elektroměru nebo měniče například
grid/import plus FVE vlastní spotřeba.

Pro `Managed hourly consumption history` má zdroj reprezentovat pouze zátěže,
které jsou záměrně řízené mimo běžný profil domu, například nabíjení EV, bojler,
ohřev vody nebo jinou řízenou spotřebu. Tato řízená spotřeba už musí být součástí
celkové spotřeby domu; Energy Planner ji po hodinách odečítá, aby se naučil
neřiditelnou základní spotřebu. Nepoužívejte zde domovní senzor už očištěný o
řízenou spotřebu, jinak by se řízená spotřeba odečetla dvakrát.

Pokud máte pouze výkonový senzor ve `W` nebo `kW`, vytvořte nejdřív Integration
(Riemann sum integral) helper pro převod výkonu na energii v `kWh` a teprve z
tohoto energetického senzoru vytvořte hodinový Utility Meter. Pro zátěže, které
se zapínají/vypínají a drží stabilní výkon, je obvykle správná integrační metoda
`left`.

První cyklus Utility Meteru je neúplný až do dalšího hodinového resetu. Energy
Planner funguje nejlépe po alespoň 3 dnech historie v Home Assistantu pro helper
spotřeby domu i helper řízené spotřeby.

### Model historie spotřeby

Když je dostupná historie Home Assistantu, Energy Planner načte poslední 3 dny
pro nakonfigurované zdroje domovní a řízené spotřeby, seskupí záznamy podle
hodiny z `last_reset`, ponechá maximální hodnotu pro každou hodinu, odečte
řízenou spotřebu od domovní spotřeby a vytvoří profil spotřeby po hodinách dne.
Například predikce pro 11:00 používá průměr předchozích hodnot z 11:00, ne
celkový průměr spotřeby domu.

Hodinový profil se navýší o Node-RED kompatibilní 5% margin a následně o
konfigurovatelné `history_correction_percent`. Pokud pro cílovou hodinu neexistuje
žádná hodnota, planner použije `min_baseline_kwh_per_hour`. Energy Planner si
také ukládá vlastní hodinovou historii jako fallback, když historie Home
Assistantu není dostupná.

### Vstupy Solcast predikce

Energy Planner čte detailní forecast atributy ze Solcast forecast senzorů v Home
Assistantu. Ve standardním nastavení Solcast PV Forecast vypadají užitečné
entity takto:

- `sensor.solcast_pv_forecast_forecast_today`
- `sensor.solcast_pv_forecast_forecast_tomorrow`
- `sensor.solcast_pv_forecast_forecast_day_3`
- `sensor.solcast_pv_forecast_forecast_day_4`

Den 5 až den 7 lze použít stejným způsobem, pokud je vaše Solcast integrace
vystavuje a má je povolené.

Pokud nakonfigurujete pouze `sensor.solcast_pv_forecast_forecast_today`, Energy
Planner automaticky hledá standardní sourozenecké entity pojmenované
`forecast_tomorrow` a `forecast_day_3` až `forecast_day_7`. Je to jen pohodlné
hledání podle názvu; integrace nesyntetizuje ani neextrapoluje budoucí solární
data. Pokud vaše Solcast entity používají jiné názvy, vyberte zítřek a další
dny predikce v setup formuláři explicitně.

Pro 24hodinovou predikci obvykle stačí dnešek a zítřek. Pro delší horizonty, nebo
pozdě večer, kdy z dneška zbývá méně dat, povolte a vyberte alespoň
`forecast_day_3`.

### Provozní možnosti

Runtime chování se mění přes Options Flow: interval plánování, korekce historie,
základní spotřeba, limity nabíjení ze sítě, NT okna, nabíjecí okno a horizont
predikce.

Hodnoty změníte v Settings > Devices & services > Energy Planner > Configure.

| Položka v UI | Key | Default | Povolená hodnota | Popis |
|--------------|-----|---------|------------------|-------|
| Interval plánování v minutách | `interval_minutes` | `5` | Kladné číslo, které beze zbytku dělí 60. | Časový krok používaný pro simulaci planneru a forecast sloty. Běžné hodnoty jsou `5`, `10`, `15`, `30` nebo `60`. |
| Korekce historie v procentech | `history_correction_percent` | `5.0` | Větší než `-100` a nejvýše `500`. | Dodatečné procento aplikované po výpočtu hodinového profilu spotřeby. Použijte pro sladění nebo doladění legacy Node-RED chování `history_correction`. |
| Minimální základní spotřeba v kWh za hodinu | `min_baseline_kwh_per_hour` | `0.2` | `0` nebo vyšší. | Fallback hodinová spotřeba domu, když cílová hodina nemá použitelný historický vzorek. |
| Maximální výkon nabíjení ze sítě v kW | `grid_charge_max_kw` | `5.5` | `0` nebo vyšší. | Maximální výkon, který simulace může použít při plánování nabíjení ze sítě během nabíjecího okna. |
| Účinnost nabíjení ze sítě | `grid_charge_efficiency` | `0.92` | Větší než `0` a nejvýše `1`. | Účinnost nabíjení baterie použitá při převodu energie ze sítě na uloženou energii v baterii. |
| Rezerva SoC v procentech | `soc_reserve_percent` | `1` | Od `0` do `100`. | Dodatečná SoC rezerva přičtená k vypočteným hodnotám lock/target. |
| Tolerance SoC v kWh | `soc_eps_kwh` | `0.02` | `0` nebo vyšší. | Malá energetická tolerance baterie používaná plannerem, aby rozhodování nebylo nestabilní kolem přesných prahů. |
| Okna nízkého tarifu | `nt_windows` | `17:00-19:00,22:00-04:00` | Jedno nebo více oken `HH:MM-HH:MM` oddělených čárkou. | Okna, ve kterých se vyhodnocuje ochrana pro nízký/vysoký tarif. Okna mohou přecházet přes půlnoc. |
| Nabíjecí okno | `charge_window` | `22:00-04:00` | Jedno okno `HH:MM-HH:MM`. | Okno, ve kterém může být v simulaci plánované nabíjení ze sítě. Okno může přecházet přes půlnoc. |
| Minimální trvání začátku solární výroby v minutách | `sun_start_required_minutes` | `30` | Větší než `0`. | Minimální souvislá forecastovaná solární perioda, než planner považuje solární výrobu za zahájenou. |
| Horizont predikce v hodinách | `forecast_horizon_hours` | `36` | Alespoň `24`. | Budoucí horizont používaný pro SoC predikci a plánování. Delší horizonty vyžadují odpovídající budoucí Solcast data. |

## Výstupní entity

Energy Planner vytváří pouze senzorové entity. Ve verzi v1 nevytváří switche,
numbers, selects ani žádné entity pro ovládání zařízení.

Níže uvedená entity ID jsou typické defaulty pro instanci integrace pojmenovanou
`Energy Planner`. Home Assistant může přidat suffix nebo použít přejmenovaná
entity ID, pokud dojde ke konfliktu nebo pokud entity ručně přejmenujete. Skutečná
ID zkontrolujte v Settings > Devices & services > Energy Planner > Entities.

| Typické entity ID | Output key | Kategorie | Jednotka/typ | Popis |
|-------------------|------------|-----------|--------------|-------|
| `sensor.energy_planner_state` | `state` | Diagnostika | text | Stav planneru: `ok`, `warning` nebo `insufficient_data`. Atributy obsahují warnings, počet slotů a kompaktní stav historie. |
| `sensor.energy_planner_lock_soc` | `lock_soc` | Standardní | `%` | Minimální SoC, které planner chce chránit pro plánovací okno nízkého/vysokého tarifu. |
| `sensor.energy_planner_charge_to_soc` | `charge_to_soc` | Standardní | `%` | Volitelný cílový SoC pro nabíjení ze sítě potřebný k pokrytí forecastovaného deficitu ve vysokém tarifu z nakonfigurovaného nabíjecího okna. |
| `sensor.energy_planner_target_soc` | `target_soc` | Standardní | `%` | Finální cílové SoC použité plannerem; aktuálně vyšší hodnota z `lock_soc` a `charge_to_soc`. |
| `sensor.energy_planner_safe_discharge_soc` | `safe_discharge_soc` | Standardní | `%` | Nejnižší SoC, na které planner považuje za bezpečné vybít baterii při zachování budoucího plánu. |
| `sensor.energy_planner_free_capacity_soc` | `free_capacity_soc` | Standardní | `%` | Aktuální SoC nad `safe_discharge_soc`, vyjádřené jako procento baterie. |
| `sensor.energy_planner_free_capacity` | `free_capacity_kwh` | Standardní | `kWh` | Aktuální energie nad `safe_discharge_soc`, vyjádřená jako kapacita baterie. |
| `sensor.energy_planner_unused_surplus_today` | `unused_surplus_today_kwh` | Standardní | `kWh` | Forecastovaný FVE přebytek pro dnešek, který simulovaný plán neumí uložit nebo využít. |
| `sensor.energy_planner_unused_surplus_total` | `unused_surplus_total_kwh` | Standardní | `kWh` | Forecastovaný FVE přebytek přes nakonfigurovaný forecast horizont, který simulovaný plán neumí uložit nebo využít. |
| `sensor.energy_planner_first_full_time` | `first_full_time` | Standardní | timestamp | První forecastovaný čas, kdy baterie dosáhne plného SoC. |
| `sensor.energy_planner_high_tariff_grid_import_at_target` | `vt_grid_import_kwh_at_target` | Standardní | `kWh` | Forecastovaný zbývající odběr ze sítě ve vysokém tarifu v simulaci při nabití na `target_soc`. |
| `sensor.energy_planner_charged_total_at_target` | `charged_kwh_total_at_target` | Standardní | `kWh` | Celková energie ze sítě, kterou simulace nabije do baterie pro dosažení `target_soc`. |
| `sensor.energy_planner_soc_at_planner_start` | `soc_at_planner_start` | Diagnostika | `%` | Predikované SoC na začátku plánovacího okna. |
| `sensor.energy_planner_soc_at_lock_start` | `soc_at_lock_start` | Diagnostika | `%` | Predikované SoC na začátku lock/protection okna. |
| `sensor.energy_planner_soc_forecast` | `soc_forecast` | Standardní | `%` | Stav je predikované SoC v nakonfigurovaném forecast horizontu. Atributy obsahují `horizon_hours`, `source` a kompaktní budoucí pole `points` pro grafové karty. |
| `sensor.energy_planner_soc_forecast_24h` | `soc_forecast_24h` | Standardní | `%` | Predikované SoC přesně 24 hodin od času výpočtu. Atribut `point` obsahuje kompletní forecast bod. |
| `sensor.energy_planner_solar_start` | `sun_start` | Diagnostika | timestamp | Začátek další použitelné periody solární výroby detekované z forecast slotů. |
| `sensor.energy_planner_lock_start` | `lock_start` | Diagnostika | timestamp | Začátek období, pro které je relevantní vypočtené lock SoC. |
| `sensor.energy_planner_updated` | `updated` | Diagnostika | timestamp | Čas posledního úspěšného výpočtu coordinatoru. |
| `sensor.energy_planner_history_status` | `history_status` | Diagnostika | text | Kompaktní stav zdroje historie spotřeby a pokrytí použitého plannerem. |

SoC predikce obsahuje alespoň 24 hodin a může použít delší nakonfigurovaný
horizont, pokud jsou dostupná zdrojová data z Home Assistantu.
Forecast hodnoty `soc_percent` jsou zaokrouhlené na celá procenta, protože
většina FVE a bateriových systémů neposkytuje smysluplnou přesnost SoC na
desetiny.

## Příklady dashboardu

Entity ID se mohou lišit, pokud Home Assistant už měl konfliktní názvy.
Zkontrolujte skutečná entity ID v Settings > Devices & services > Energy
Planner > Entities a příklady podle potřeby upravte.

### Budoucí SoC predikce přes ApexCharts

Celá budoucí SoC křivka je vystavená na senzoru `soc_forecast` jako kompaktní
atribut `points`. Stav samotného senzoru je jen SoC v nakonfigurovaném forecast
horizontu.

Nainstalujte `apexcharts-card` přes HACS a přidejte manuální kartu:

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: hour
locale: cs
header:
  title: Forecast SoC
  show: true
  show_states: true
  colorize_states: true
now:
  show: true
  label: Now
yaxis:
  - min: 0
    max: 100
    decimals: 0
series:
  - entity: sensor.energy_planner_soc_forecast
    name: Predikce SoC
    type: area
    opacity: 0.35
    stroke_width: 2
    unit: "%"
    show:
      in_header: raw
      extremas: true
    data_generator: |
      const points = entity.attributes.points || [];
      return points
        .filter((point) => point.timestamp && point.soc_percent !== undefined)
        .map((point) => {
          return [new Date(point.timestamp).getTime(), Number(point.soc_percent)];
        });
```

Důležitá část je `entity.attributes.points`. Každý bod používá `timestamp` a
`soc_percent`; nepoužívejte `entity.points`, `time` ani `SoC`.

Tento příklad záměrně zobrazuje příštích 24 hodin. Pokud máte nakonfigurovaný
delší forecast horizont a dodáváte také delší Solcast forecast vstupy, navyšte
`graph_span`.

Pokud je karta prázdná:

- Ověřte v Developer Tools > States, že `sensor.energy_planner_soc_forecast` má atribut `points`.
- Nahraďte entity ID, pokud Home Assistant vytvořil lokalizovaný nebo suffixovaný název.
- Spusťte službu `energy_planner.recalculate` a obnovte dashboard.
- Po instalaci nebo aktualizaci `apexcharts-card` vyčistěte cache prohlížeče.

### Budoucí nevyužitý FVE přebytek přes ApexCharts

Každý forecast bod obsahuje také `unused_surplus_kwh`, což je přebytečná energie
pro daný plánovací slot. Příklad níže převádí energii slotu na ekvivalentní
výkon v `kW` podle intervalu mezi forecast body. Pro 5minutový interval planneru
je to stejné jako vynásobit slotové `kWh` hodnotou `12`.

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: hour
locale: cs
header:
  title: Forecast unused PV surplus
  show: true
  colorize_states: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_soc_forecast
    name: Nevyužitý přebytek
    type: area
    opacity: 0.45
    stroke_width: 2
    unit: kW
    show:
      extremas: true
    data_generator: |
      const points = entity.attributes.points || [];
      const first = new Date(points[0]?.timestamp).getTime();
      const second = new Date(points[1]?.timestamp).getTime();
      const intervalHours =
        Number.isFinite(first) && Number.isFinite(second) && second > first
          ? (second - first) / 3600000
          : 1;

      return points
        .map((point) => {
          const timestamp = new Date(point.timestamp).getTime();
          if (!Number.isFinite(timestamp)) {
            return null;
          }
          const surplusKwh = Number(point.unused_surplus_kwh ?? 0);
          return [
            timestamp,
            Number.isFinite(surplusKwh) ? surplusKwh / intervalHours : 0,
          ];
        })
        .filter((point) => point !== null);
```

Pokud chcete zobrazit přímo energii v plánovacím slotu, změňte `unit` na `kWh`
a vracejte `surplusKwh` místo `surplusKwh / intervalHours`.

### Samostatná 24hodinová hodnota SoC

Pro jednoduchou hodnotu v dashboardu použijte dedikovaný 24hodinový senzor:

```yaml
type: gauge
entity: sensor.energy_planner_soc_forecast_24h
name: SoC za 24 hodin
min: 0
max: 100
severity:
  green: 50
  yellow: 25
  red: 0
```

Tento senzor je běžná číselná entita, takže vestavěné karty `tile`, `gauge`,
`history-graph` a `statistics-graph` umí zobrazit historii jeho stavů. Tato
historie ukazuje, jak se predikované 24hodinové SoC mění v čase; není to celá
budoucí forecast křivka. Pro kompletní budoucí křivku použijte výše uvedený
příklad s atributy pro ApexCharts.

## Služby

- `energy_planner.recalculate` obnoví planner data pro načtené config entry.
- `energy_planner.export_debug` zapíše kompaktní debug data do logu a vystřelí
  event `energy_planner_debug_exported`.

Služby neovládají zařízení.

## Řešení problémů

- `insufficient_data` znamená, že povinná zdrojová entita chybí, je unavailable nebo není číselná.
- `warning` obvykle znamená, že volitelná data, například Solcast forecast, chybí nebo mají chybný formát.
- Diagnostiku z integrační stránky použijte pro kontrolu nakonfigurovaných entit, posledního stavu planneru, warnings a shrnutí plánu.
- Debug payloady nedávejte do běžných stavových atributů; použijte diagnostiku nebo `energy_planner.export_debug`.

## Vývojová validace

```bash
uv run --extra ha --extra dev ruff check .
uv run --extra ha --extra dev ruff format --check .
uv run --extra ha --extra dev pytest -q
```

Release candidate musí projít také Hassfest a HACS Action v GitHub Actions.

## Migrace z Node-RED

Tato integrace nahrazuje aktivní Node-RED flow `Energy Prediction 2` testovanou
integrací pro Home Assistant.

Jako parity reference se používá pouze aktivní výpočetní větev Node-RED. Backupy,
datované archivy a odpojené Node-RED nody se ignorují.

Lokální soubor `nodered_export.json` je záměrně ignorovaný Gitem a nesmí být
publikován. Parity testy používají sanitizované fixtures odvozené z pochopeného
chování aktivního flow, ne raw Node-RED kód.

Důležité migrační poznámky:

- v1 vystavuje pouze planner senzory a neovládá zařízení.
- `lock_soc` zachovává rezervu baterie pro NT/VT plánování.
- `charge_to_soc` je volitelný cíl nabíjení ze sítě pro nakonfigurované nabíjecí okno.
- `free_capacity_kwh` znamená bezpečně vybitelnou energii nad `safe_discharge_soc`.
- Legacy flow přidává 1 procentní bod ke nakonfigurovanému minimálnímu SoC baterie před použitím jako efektivní floor; parity fixtures to modelují explicitně.
- Predikce spotřeby odpovídá hodinovému profilu aktivního flow: poslední 3 dny historie HA, seskupené podle `last_reset`, řízená spotřeba odečtená po hodinách, plus 5% history margin.
- Čistý planner může vystavovat čistší formát timestampů a kompaktní forecast atributy při zachování hlavních plánovacích výstupů.

Viz `SPECIFICATION.md` a `CODEX_IMPLEMENTATION_PROMPT.md`.

## Upozornění

Software je poskytován tak, jak je, bez záruky a bez garance podpory. Omezení
rizik a podpory projektu najdete v `DISCLAIMER.md`.
