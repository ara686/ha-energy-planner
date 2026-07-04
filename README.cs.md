# ha-energy-planner

[English](README.md) | Česky

Vlastní integrace pro Home Assistant pro plánování FVE, baterie, tarifů a EV.

> [!WARNING]
> Energy Planner je experimentální software v aktivním vývoji. Není doporučen pro produkční použití. Instalaci a používání provádíte na vlastní riziko. Nespoléhejte na něj pro bezpečnostně kritická, životně důležitá, majetkově ochranná, nouzová, provozní, finanční, fakturační, regulatorní ani compliance rozhodnutí.

Integrace pouze počítá výstupy energetického plánování. Ve verzi v1 **neovládá**
Victron, EV nabíječky, topení ani jiná zařízení. Pokud její senzory použijete v
automatizacích, odpovídáte za ověření chování automatizace a za všechny důsledky
těchto automatizací.

## Účel a provozní model

Energy Planner odhaduje, jak se bude vyvíjet stav nabití baterie podle naučené
hodinové spotřeby domu a očekávané solární výroby. Z historie Home Assistantu
si sestaví profil spotřeby podle hodin dne, odečte nakonfigurované řízené
spotřeby od běžné základní spotřeby domu a zkombinuje to se Solcast forecast
daty, která už jsou dostupná v Home Assistantu.

Integrace publikuje forecast data vhodná pro grafy a pomocné senzory použitelné
v samostatných automatizacích. Predikce SoC ukazuje, jak se baterie pravděpodobně
bude vyvíjet v dalších 24 hodinách nebo delším horizontu. Výstup lock SoC říká,
kolik kapacity baterie má zůstat chráněné, aby bylo možné překlenout
nakonfigurované období vysokého tarifu bez odběru ze sítě. Výstup charge-to SoC
říká, na kolik by bylo potřeba baterii nabít v nízkém tarifu, aby šlo pozdější
období vysokého tarifu překlenout.

Energy Planner také odhaduje nevyužitý solární přebytek. Ten můžete použít ve
vlastních automatizacích pro rozhodnutí, kdy spustit flexibilní zátěže jako
ohřev TUV, bazénovou technologii nebo nabíjení EV. Tyto flexibilní zátěže by
měly být nastavené jako řízené energetické zdroje, aby se jejich spotřeba
neučila jako běžná základní spotřeba domu.

Ve verzi v1 Energy Planner nic přímo nespíná ani neovládá. Připravuje data a
entity pro dashboardy a pro automatizace, které si uživatel spravuje sám.

### Typická strategie pro tarif D25d

U českého tarifu D25d s osmi hodinami nízkého tarifu je typická letní strategie
odhadovat denní solární přebytek a využít ho pro flexibilní spotřebu, například
bojler, bazén nebo nabíjení EV. V zimním a přechodném období se strategie obvykle
posouvá k maximálnímu využití nízkého tarifu a překlenutí období vysokého tarifu.
Podle forecastu to může znamenat i nabití baterie během nízkého tarifu tak, aby
šel vysoký tarif přeskočit s minimálním nebo žádným odběrem ze sítě.

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

## Odstranění

Energy Planner odstraníte takto:

1. Otevřete Settings > Devices & services > Energy Planner.
2. V menu integrační položky zvolte Delete.
3. Pokud byla integrace nainstalovaná přes HACS, odstraňte Energy Planner také z
   HACS.
4. Restartujte Home Assistant, pokud si Home Assistant po odstranění souborů
   vlastní integrace vyžádá restart.

Odstranění integrační položky smaže také interně uloženou historii spotřeby
Energy Planneru pro danou položku. Neodstraní původní zdrojové entity, helpery,
dashboardy ani automatizace, které odkazují na senzory Energy Planneru.

## Konfigurace

Energy Planner se konfiguruje pouze přes UI Home Assistantu. Očekává už
existující zdrojové entity v Home Assistantu a vlastní hodinovou historii
spotřeby si vede interně; Utility Meter helpery už vytvářet nemusíte.

Formuláře pro setup a reconfigure filtrují výběr entit podle očekávané domény a
device class, pokud tato metadata Home Assistant u entity poskytuje. Submit
validace potom vynucuje přesné požadavky na jednotku a state class. Například
kapacita baterie musí být kladná entita v `kWh`, zatímco spotřeba domu a řízené
spotřeby jsou kumulativní energetické senzory v `kWh`.

Po nastavení použijte **Nastavení > Zařízení a služby > Energy Planner >
Reconfigure** pro změnu vstupních entit bez mazání a opětovného přidání
integrace.

### Vstupní entity

Tyto hodnoty se vybírají v setup UI. Sloupec `Key` je uložený konfigurační klíč
používaný v diagnostice a debug výstupech.

| Položka v setupu | Key | Povinné | Očekávaný vstup | Poznámky a příklady |
|------------------|-----|---------|-----------------|---------------------|
| Stav nabití baterie | `battery_soc_entity` | Povinné | Číselný senzor SoC baterie v `%`. | Použijte SoC entitu z integrace FVE/bateriového měniče, například Victron, GoodWe, Solax, Huawei nebo SolarEdge. |
| Kapacita baterie | `battery_capacity_entity` | Povinné | Číselný senzor kapacity baterie v `kWh`. | Použijte entitu z měniče/BMS, pokud existuje. Pokud je kapacita fixní a měnič ji neposkytuje, vytvořte v Home Assistantu helper s nastavenou hodnotou kapacity. |
| Minimální stav nabití baterie | `battery_min_soc_entity` | Povinné | Číselný senzor minimálního/rezervního SoC v `%`. | Použijte entitu minimálního SoC z měniče/BMS. Pokud systém má jen fixní rezervu, vytvořte pro ni helper. |
| Zdroj energie spotřeby domu | `home_energy_entity` | Povinné | Kumulativní senzor celkové spotřeby domu v `kWh`. | Použijte total/total-increasing energetický senzor spotřeby domu. Energy Planner z něj interně sestaví hodinovou historii. |
| Zdroje řízené spotřeby | `managed_energy_entities` | Volitelné | Žádný, jeden nebo více kumulativních energetických senzorů v `kWh`. | Vyberte záměrně řízené zátěže, například nabíjení EV, bojler nebo ohřev vody. Tyto hodnoty se sečtou a po hodinách odečítají od spotřeby domu. |
| Solcast predikce pro dnešek | `solcast_today_entity` | Volitelné | Solcast forecast senzor z Home Assistantu. | Příklad: `sensor.solcast_pv_forecast_forecast_today`. Energy Planner čte pouze data z Home Assistantu a nevolá Solcast přímo. |
| Solcast predikce pro zítřek | `solcast_tomorrow_entity` | Volitelné | Solcast forecast senzor z Home Assistantu. | Příklad: `sensor.solcast_pv_forecast_forecast_tomorrow`. Pokud entita pro dnešek používá standardní Solcast naming pattern, Energy Planner umí tuto sourozeneckou entitu najít automaticky. |
| Další dny Solcast predikce | `solcast_additional_entities` | Volitelné | Jedna nebo více Solcast forecast entit z Home Assistantu. | Příklady: `sensor.solcast_pv_forecast_forecast_day_3`, `sensor.solcast_pv_forecast_forecast_day_4`. Standardní sourozenci `forecast_day_3` až `forecast_day_7` mohou být automaticky nalezeni, pokud existují. |
| Cena nebo tarif | `price_entity` | Volitelné | Číselný senzor ceny/tarifu nebo stavová entita tarifu. | Rezervováno pro plánování a diagnostiku podle tarifů. Aktuální v1 planner z tohoto vstupu neovládá zařízení. |

### Energetické zdroje spotřeby

Energy Planner potřebuje kumulativní energetické hodnoty, ne okamžité hodnoty
výkonu. Pro domovní zdroj vyberte senzor, který reprezentuje celkovou spotřebu
domu v `kWh`. Dobré zdroje jsou podle dostupných dat z elektroměru nebo měniče
například grid/import plus FVE vlastní spotřeba.

Pro `Zdroje řízené spotřeby` vyberte pouze zátěže, které jsou záměrně řízené
mimo běžný profil domu, například nabíjení EV, bojler, ohřev vody nebo jinou
řízenou spotřebu. Tato řízená spotřeba už musí být součástí celkové spotřeby
domu; Energy Planner ji po hodinách odečítá, aby se naučil neřiditelnou základní
spotřebu. Nepoužívejte domovní senzor už očištěný o řízenou spotřebu, jinak by
se řízená spotřeba odečetla dvakrát.

Pokud máte pouze výkonový senzor, například `sensor.home_power` v `W`, vytvořte
nejdřív v Home Assistantu Integral helper, který převede výkon na energii v
`kWh`, a tento nový energetický senzor vyberte v Energy Planneru. V Home
Assistantu vytvořte Integration (Riemann sum integral) helper z výkonového
senzoru, nastavte výstupní jednotku na `kWh` a vzniklý kumulativní energetický
senzor použijte jako `home_energy_entity`. Toto dělejte jen tehdy, když už
nemáte vhodný `kWh` energetický senzor přímo. Neintegrujte entitu, která už je
kumulativní energie v `kWh`. Pro zátěže, které se zapínají/vypínají a drží
stabilní výkon, je obvykle správná integrační metoda `left`.

Energy Planner sestavuje hodinové buckety interně z kladných delt vybraných
kumulativních energetických senzorů. První hodnota je pouze baseline; použitelná
historie vzniká po další změně zdroje nebo z historie Home Assistant recorderu.
Při nové instalaci bez existující recorder historie pro vybrané zdroje se první
rozumné výsledky obvykle objeví přibližně po 24 hodinách. Profil bude výrazně
přesnější přibližně po 48 hodinách, protože planner už vidí alespoň dva vzorky
pro stejnou hodinu dne.

### Model historie spotřeby

Když je dostupná historie Home Assistantu, Energy Planner načte nakonfigurovaný
počet dní historie pro zdroje domovní a řízené spotřeby, spočítá kladné delty
kumulativních hodnot, zařadí je do hodinových bucketů, odečte řízenou spotřebu od
domovní spotřeby a vytvoří profil spotřeby po hodinách dne. Například predikce
pro 11:00 používá průměr předchozích hodnot z 11:00, ne celkový průměr spotřeby
domu.

Hodinový profil se navýší o vestavěný 5% history margin a následně o
konfigurovatelné `history_correction_percent`. Pokud pro cílovou hodinu
neexistuje žádná hodnota, planner použije `min_baseline_kwh_per_hour`. Energy
Planner si také ukládá vlastní hodinovou historii jako fallback, když historie
Home Assistantu není dostupná.

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

Runtime chování se mění přes Options Flow: automatický interval přepočtu, počet
dní historie spotřeby, interval plánování, korekce historie, základní spotřeba,
limity nabíjení ze sítě, NT okna, nabíjecí okno a horizont predikce.

Hodnoty změníte v Settings > Devices & services > Energy Planner > Configure.
Stejné hodnoty jsou vystavené také jako read-only diagnostické senzory, takže v
Home Assistantu vidíte přesně aktivní nastavení a můžete na ně odkazovat ze
stavů.
Uvedená entity ID jsou typické defaulty; skutečná ID ověřte v Home Assistantu,
pokud je změnil jazyk backendu, konflikt názvů nebo ruční přejmenování.

| Položka v UI | Key | Diagnostická entita | Default | Povolená hodnota | Popis |
|--------------|-----|---------------------|---------|------------------|-------|
| Interval přepočtu v minutách | `update_interval_minutes` | `sensor.energy_planner_interval_prepoctu` | `60` | Kladné číslo. | Automatický polling planneru. Změna stavu baterie SoC zároveň spustí okamžitý přepočet, takže planner může reagovat ještě před dalším periodickým během. |
| Počet dní historie spotřeby | `history_learning_days` | `sensor.energy_planner_pocet_dni_historie_spotreby` | `3` | Kladné celé číslo. | Počet dní historie Home Assistantu použitých pro sestavení hodinového profilu spotřeby. |
| Interval plánování v minutách | `interval_minutes` | `sensor.energy_planner_interval_planovani` | `5` | Kladné číslo, které beze zbytku dělí 60. | Časový krok používaný pro simulaci planneru a forecast sloty. Běžné hodnoty jsou `5`, `10`, `15`, `30` nebo `60`. |
| Korekce historie v procentech | `history_correction_percent` | `sensor.energy_planner_korekce_historie` | `5.0` | Větší než `-100` a nejvýše `500`. | Dodatečné procento aplikované po výpočtu hodinového profilu spotřeby. Použijte pro doladění naučeného profilu spotřeby. |
| Minimální základní spotřeba v kWh za hodinu | `min_baseline_kwh_per_hour` | `sensor.energy_planner_minimalni_zakladni_spotreba` | `0.2` | `0` nebo vyšší. | Fallback hodinová spotřeba domu, když cílová hodina nemá použitelný historický vzorek. |
| Maximální výkon nabíjení ze sítě v kW | `grid_charge_max_kw` | `sensor.energy_planner_maximalni_nabijeni_ze_site` | `5.5` | `0` nebo vyšší. | Maximální výkon, který simulace může použít při plánování nabíjení ze sítě během nabíjecího okna. |
| Účinnost nabíjení ze sítě | `grid_charge_efficiency` | `sensor.energy_planner_ucinnost_nabijeni_ze_site` | `0.92` | Větší než `0` a nejvýše `1`. | Účinnost nabíjení baterie použitá při převodu energie ze sítě na uloženou energii v baterii. |
| Rezerva SoC v procentech | `soc_reserve_percent` | `sensor.energy_planner_rezerva_soc` | `1` | Od `0` do `100`. | Dodatečná SoC rezerva přičtená k vypočteným hodnotám lock/target. |
| Tolerance SoC v kWh | `soc_eps_kwh` | `sensor.energy_planner_tolerance_soc` | `0.02` | `0` nebo vyšší. | Malá energetická tolerance baterie používaná plannerem, aby rozhodování nebylo nestabilní kolem přesných prahů. |
| Okna nízkého tarifu | `nt_windows` | `sensor.energy_planner_okna_nizkeho_tarifu` | `17:00-19:00,22:00-04:00` | Jedno nebo více oken `HH:MM-HH:MM` oddělených čárkou. | Okna, ve kterých se vyhodnocuje ochrana pro nízký/vysoký tarif. Okna mohou přecházet přes půlnoc. |
| Nabíjecí okno | `charge_window` | `sensor.energy_planner_okno_pro_nabijeni` | `22:00-04:00` | Jedno okno `HH:MM-HH:MM`. | Okno, ve kterém může být v simulaci plánované nabíjení ze sítě. Okno může přecházet přes půlnoc. |
| Minimální trvání začátku solární výroby v minutách | `sun_start_required_minutes` | `sensor.energy_planner_minimalni_delka_solarniho_startu` | `30` | Větší než `0`. | Minimální souvislá forecastovaná solární perioda, než planner považuje solární výrobu za zahájenou. |
| Horizont predikce v hodinách | `forecast_horizon_hours` | `sensor.energy_planner_horizont_predikce` | `36` | Alespoň `24`. | Budoucí horizont používaný pro SoC predikci a plánování. Delší horizonty vyžadují odpovídající budoucí Solcast data. |

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
| `sensor.energy_planner_history_status` | `history_status` | Diagnostika, vypnuto ve výchozím stavu | text | Kompaktní stav zdroje historie spotřeby a pokrytí použitého plannerem. Detail je dostupný také v diagnostice integrace. |
| `sensor.energy_planner_consumption_history` | `consumption_history` | Diagnostika | `kWh` | Poslední hodinový bucket základní spotřeby použitý plannerem. Atributy obsahují kompaktní hodinové `points` s hodnotami `home_kwh`, `managed_kwh` a `base_kwh` pro grafové karty. |

Pouze `sensor.energy_planner_soc_forecast` používá v Home Assistantu `battery`
device class. Ostatní SoC výstupy jsou plánovací cíle, limity nebo pomocné
budoucí hodnoty, takže zůstávají obyčejnými procentními senzory a nejsou
vystavené jako senzory úrovně baterie.

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

### Historie spotřeby přes ApexCharts

Stav `sensor.energy_planner_consumption_history` je poslední hodinový bucket
základní spotřeby v `kWh`. Atribut `points` obsahuje hodinovou historii, kterou
planner používá. Každý bod obsahuje:

- `home_kwh`: celkovou spotřebu domu v dané hodině.
- `managed_kwh`: záměrně řízenou spotřebu v dané hodině.
- `base_kwh`: `home_kwh - managed_kwh`, nejméně nula.

Senzor vystavuje nejvýše posledních 168 hodinových bodů. Pokud je nakonfigurované
okno historie delší, atribut `truncated` bude `true`.

```yaml
type: custom:apexcharts-card
graph_span: 3d
span:
  end: hour
locale: cs
header:
  title: Historie spotřeby
  show: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_consumption_history
    name: Dům
    type: column
    unit: kWh
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.home_kwh ?? 0),
      ]);
  - entity: sensor.energy_planner_consumption_history
    name: Řízená spotřeba
    type: column
    unit: kWh
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.managed_kwh ?? 0),
      ]);
  - entity: sensor.energy_planner_consumption_history
    name: Základ
    type: line
    unit: kWh
    stroke_width: 2
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.base_kwh ?? 0),
      ]);
```

### Historie home power a managed power přes ApexCharts

Pokud chcete v jednom výkonovém grafu porovnat celkovou spotřebu domu a řízenou
spotřebu, použijte stejný atribut `points` a převeďte každý hodinový energetický
bucket na průměrný výkon. Pro hodinové buckety platí, že `kWh / 1 h` je průměrný
výkon v `kW`.

```yaml
type: custom:apexcharts-card
graph_span: 3d
span:
  end: hour
locale: cs
header:
  title: Historie výkonu domu a řízené spotřeby
  show: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_consumption_history
    name: Výkon domu
    type: column
    unit: kW
    data_generator: |
      const points = entity.attributes.points || [];

      const intervalHours = (index) => {
        const current = new Date(points[index]?.timestamp).getTime();
        const next = new Date(points[index + 1]?.timestamp).getTime();
        const previous = new Date(points[index - 1]?.timestamp).getTime();
        if (Number.isFinite(current) && Number.isFinite(next) && next > current) {
          return (next - current) / 3600000;
        }
        if (Number.isFinite(previous) && Number.isFinite(current) && current > previous) {
          return (current - previous) / 3600000;
        }
        return 1;
      };

      return points.map((point, index) => {
        const timestamp = new Date(point.timestamp).getTime();
        const hours = intervalHours(index);
        return [
          timestamp,
          Number(point.home_kwh ?? 0) / hours,
        ];
      });
  - entity: sensor.energy_planner_consumption_history
    name: Výkon řízené spotřeby
    type: column
    unit: kW
    data_generator: |
      const points = entity.attributes.points || [];

      const intervalHours = (index) => {
        const current = new Date(points[index]?.timestamp).getTime();
        const next = new Date(points[index + 1]?.timestamp).getTime();
        const previous = new Date(points[index - 1]?.timestamp).getTime();
        if (Number.isFinite(current) && Number.isFinite(next) && next > current) {
          return (next - current) / 3600000;
        }
        if (Number.isFinite(previous) && Number.isFinite(current) && current > previous) {
          return (current - previous) / 3600000;
        }
        return 1;
      };

      return points.map((point, index) => {
        const timestamp = new Date(point.timestamp).getTime();
        const hours = intervalHours(index);
        return [
          timestamp,
          Number(point.managed_kwh ?? 0) / hours,
        ];
      });
```

## Akce a služby

Energy Planner poskytuje tyto Home Assistant service actions:

- `energy_planner.recalculate` obnoví planner data pro načtené config entry.
- `energy_planner.export_debug` zapíše kompaktní debug data do logu a vystřelí
  event `energy_planner_debug_exported`.

Služby neovládají zařízení.

## Triggery a conditions

Energy Planner ve verzi v1 neposkytuje automation triggers ani automation
conditions. Pro automatizace použijte standardní Home Assistant state, numeric
state, time nebo template triggery nad senzory Energy Planneru.

## Řešení problémů

- `insufficient_data` znamená, že povinná zdrojová entita chybí, je unavailable nebo není číselná.
- `error` s `Battery capacity must be greater than zero` znamená, že nastavená
  `battery_capacity_entity` není kladná kapacita baterie v `kWh`. Nepoužívejte
  entity proudu ani instalované kapacity v `Ah`; použijte entitu kapacity v
  `kWh` nebo Home Assistant helper s pevnou kapacitou baterie.
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

Viz `SPECIFICATION.md` a `CODEX_IMPLEMENTATION_PROMPT.md`.

## Upozornění

Software je poskytován tak, jak je, bez záruky a bez garance podpory. Omezení
rizik a podpory projektu najdete v `DISCLAIMER.md`.
