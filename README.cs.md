# Energy Planner pro Home Assistant

[English](README.md) | Česky

Energy Planner pomáhá uživatelům Home Assistantu odhadnout, co se bude dít s
domácí baterií během dalšího dne. Kombinuje nedávnou spotřebu domu, volitelné
řízené spotřebiče a Solcast předpověď FVE, která už existuje v Home Assistantu.

> [!WARNING]
> Energy Planner je experimentální software v aktivním vývoji. Není doporučený
> pro produkční použití. Instalaci a používání provádíte na vlastní riziko.
> Nespoléhejte se na něj pro bezpečnostní, životně důležitá, majetková,
> havarijní, provozní, finanční, fakturační, regulatorní ani compliance
> rozhodnutí.

Energy Planner **sám nic neovládá**. Pouze vytváří senzory a binární senzory,
které můžete použít v dashboardech nebo ve vlastních automatizacích.

## S čím pomůže

- Porovná pasivní predikci SoC baterie s druhou predikcí, která započítává
  očekávanou řízenou spotřebu na zítřek.
- Pomůže rozhodnout, jestli má smysl baterii nabíjet v nízkém tarifu.
- U instalací bez dvoutarifu umožní okna nízkého tarifu úplně vypnout.
- Plánování nabíjení ze sítě lze vypnout nezávisle, pokud se baterie ze sítě
  nabíjet nemá.
- Ukáže, jestli je podle plánu ještě povolené vybíjení baterie.
- Odhadne nevyužitý přebytek z FVE pro bojler, bazén, ohřev vody nebo EV.
- Doporučí rozdělení úplně pokrytého budoucího přebytku mezi typované řízené
  odběry. Obecné odběry používají historii nebo entitu s požadavkem, zásobník
  TUV aktuální teploty a fyzikální parametry a elektromobil aktuální požadavek
  energie do baterie a limit nabíjecího příkonu.
- Volitelně sestaví EV plán podle času odjezdu, dostupnosti auta, přebytku FVE,
  bezpečné energie domácí baterie a slotů GRIDu v nízkém i vysokém tarifu.
- Oddělí řízené spotřebiče od běžné spotřeby domu, aby se lépe učil běžný
  profil domácnosti.
- Ukáže řízené spotřebiče zvlášť, takže uvidíte spotřebu EV, TUV, bazénu nebo
  jiné řízené zátěže samostatně.

Například u tarifu D25d můžete v létě využít přebytek z FVE pro pružné
spotřebiče a v zimě lépe plánovat využití nízkého tarifu tak, aby baterie
překlenula vysoký tarif.

## Instalace

Je vyžadován Home Assistant 2025.3 nebo novější.

### HACS

1. Přidejte `https://github.com/ara686/ha-energy-planner` jako **Integration**
   custom repository v HACS.
2. Nainstalujte **Energy Planner**.
3. Restartujte Home Assistant.
4. Přidejte **Energy Planner** přes **Nastavení > Zařízení a služby**.

### Ruční instalace

1. Zkopírujte `custom_components/energy_planner` do adresáře
   `custom_components` ve vašem Home Assistantu.
2. Restartujte Home Assistant.
3. Přidejte integraci z UI.

YAML konfigurace není podporovaná.

## Co připravit před nastavením

Energy Planner se nastavuje v UI Home Assistantu. Během nastavení vyberete
existující HA entity.

Povinné:

- SoC baterie v `%`.
- Kapacita baterie v `kWh`.
- Minimální nebo rezervní SoC baterie v `%`; podporované jsou i obecné entity
  měniče typu `number`, například `number.inverter_battery_low_soc`.
- Kumulativní spotřeba celého domu v podporované jednotce energie, například
  `kWh` nebo `MWh`; Energy Planner ji normalizuje na `kWh`.

Volitelné:

- Řízené odběry přidané po společném nastavení jako samostatné položky. Dostupné
  typy jsou `generic`, `hot_water` a `electric_vehicle`; každý stále vyžaduje
  vlastní kumulativní elektroměr, aby šlo jeho spotřebu odečíst z profilu domu.
- Číselná entita požadované energie pro `generic`, nebo dvě teplotní čidla a
  parametry zásobníku pro `hot_water`. Typ `electric_vehicle` potřebuje entitu
  zbývající energie na straně baterie auta a pevný maximální výkon nabíječky v
  `kW`; typickým vstupem požadavku je template senzor
  `sensor.enyaq_charge_kwh`.
- EV plán podle odjezdu navíc potřebuje `device_tracker`, `binary_sensor`
  připojeného kabelu, pracovní dny s časy odjezdu/návratu a `input_boolean`,
  který výslovně povoluje GRID mimo nízký tarif.
- Solcast předpověď FVE pro dnešek, zítřek a další dny.

Pokud máte spotřebu domu jen jako okamžitý výkon, například
`sensor.home_power` ve `W`, vytvořte nejdřív v Home Assistantu helper
**Integral** a v Energy Planneru použijte výsledný `kWh` senzor.

Podrobný seznam vstupů, jednotek a provozních možností je v
[detailní konfiguraci](docs/configuration.md).

## První výsledky

Energy Planner staví hodinový profil spotřeby z historie Home Assistantu.

- Pokud Home Assistant už má historii vybraných energetických senzorů, rozumné
  hodnoty se mohou objevit hned.
- U nové instalace bez historie počítejte s prvními rozumnými výsledky zhruba po
  24 hodinách.
- Přesnější hodnoty čekejte zhruba po 48 hodinách, protože planner uvidí stejné
  hodiny dne vícekrát.
- Obecná doporučení založená na historii vyžadují alespoň tři dostatečně pokryté
  ukončené dny a používají až sedm posledních dní. Doporučení TUV historii
  spotřeby nepotřebuje a totéž platí pro EV. Oba modely vyžadují platné aktuální
  vstupy a úplné solární pokrytí.

Reconfigure uloženou historii zachovává. Pokud změníte zdrojovou entitu,
výsledky chvíli sledujte. Integraci smažte jen tehdy, když chcete záměrně
smazat i uloženou historii planneru.

## Hlavní entity pro použití

Skutečná entity ID se mohou lišit, pokud Home Assistant přidá suffix nebo pokud
entity ručně přejmenujete. Zkontrolujte je v **Nastavení > Zařízení a služby >
Energy Planner > Entity**.

Nejužitečnější entity:

| Entita | Význam |
|--------|--------|
| `sensor.energy_planner_soc_forecast` | Pasivně predikované SoC na konci nastaveného horizontu. Používá aktuální SoC, historii spotřeby a předpověď FVE, bez předpokladu, že automatizace Energy Planneru už baterii nabila nebo zamkla. V atributech obsahuje body pro graf. |
| `sensor.energy_planner_soc_forecast_with_managed_loads` | Pasivně predikované SoC na konci nastaveného horizontu se započteným obecným odběrem a skutečně přidělenými solárními sloty TUV a EV. Atributy obsahují kompaktní body pro graf, alokace po dnech a podrobnosti rozložení řízené spotřeby. |
| `sensor.energy_planner_soc_forecast_24h` | Pasivně predikované SoC přesně za 24 hodin od posledního výpočtu. |
| `binary_sensor.energy_planner_charge_now` | Zapnuto, když povolené plánování nabíjení ze sítě říká, že teď má smysl nabíjet. |
| `binary_sensor.energy_planner_discharge_allowed` | Zapnuto, když plán povoluje vybíjení baterie. |
| `sensor.energy_planner_target_soc` | Cílové SoC použité plannerem. |
| `sensor.energy_planner_charge_to_soc` | SoC potřebné pro plánované nabíjení ze sítě. |
| `sensor.energy_planner_safe_discharge_soc` | Nejnižší SoC, které ještě zachová plán. |
| `sensor.energy_planner_unused_surplus_today` | Odhad nevyužitého přebytku z FVE pro dnešek z pasivní predikce. |
| `sensor.energy_planner_unused_surplus_tomorrow` | Rozdělitelný přebytek na zítřek. Hodnotu má jen při pokrytí celého místního dne i solárních vstupů. |
| `sensor.energy_planner_recommended_managed_energy_today` | Celkový elektrický vstup doporučený pro EV ve zbývajících úplných slotech dneška. Při neúplném pokrytí slotů nebo solárních dat je nedostupný. |
| `sensor.energy_planner_recommended_managed_energy_tomorrow` | Celková energie doporučená pro všechny řízené odběry na zítřek. Atributy obsahují kompaktní alokace pro každý úplný budoucí místní den v horizontu. |
| `sensor.energy_planner_unallocated_surplus_tomorrow` | Zítřejší přebytek zbývající po všech doporučeních. |
| `sensor.energy_planner_managed_<source>_suggested_today` | Elektrický vstup nabíječky doporučený dnes pro `electric_vehicle`. Pro jiné typy je entita nedostupná. Typované alokace zveřejňují úplnost předpovědi a kompaktní solární timeline konkrétního zdroje. |
| `sensor.energy_planner_managed_<source>_suggested_tomorrow` | Doporučená energie pro jeden odběr. Atributy TUV obsahují plánovanou cílovou teplotu a solární timeline; atributy EV požadavek, nedostatek a jeho solární timeline. |
| `sensor.energy_planner_managed_<source>_charging_mode` | Aktuální poradní EV akce, například `connect_vehicle`, `solar`, `home_battery`, `grid_low_tariff`, `shortfall` nebo `complete`. |
| `sensor.energy_planner_managed_<source>_next_departure` | Příští nastavený místní odjezd použitý jako deadline EV. |
| `sensor.energy_planner_managed_<source>_planned_until_departure` | Elektrický vstup nabíječky naplánovaný do odjezdu. Atributy obsahují rozpad zdrojů, shortfall, důvod, další akci, variantu se solárem při autě doma a kompaktní časovou osu. |
| `sensor.energy_planner_managed_<source>_today` | Dnešní spotřeba jedné řízené zátěže, například EV nebo TUV. |
| `sensor.energy_planner_managed_<source>_tracked_total` | Sledovaný součet Energy Planneru pro jednu řízenou zátěž. |

Kompletní seznam entit je v [přehledu entit](docs/entities.md).

## Dashboardy

Dobré první dashboardy:

- Graf budoucího SoC z `sensor.energy_planner_soc_forecast`.
- Porovnávací graf z `sensor.energy_planner_soc_forecast` a
  `sensor.energy_planner_soc_forecast_with_managed_loads`.
- Gauge s hodnotou SoC za 24 hodin z `sensor.energy_planner_soc_forecast_24h`.
- Graf nevyužitého přebytku FVE.
- Graf spotřeby domu proti řízené spotřebě.
- Graf řízených spotřebičů zvlášť, například EV a TUV jako samostatné řady.
- Informační karty plánů TUV a EV s lidským souhrnem, přesnými časovými okny
  a společným přehledem domácnosti.

Lovelace a ApexCharts ukázky jsou v [dashboard příkladech](docs/dashboard.md).
Screenshoty se dají později doplnit tam, bez zbytečného natahování hlavního
README.

## Nápady na automatizace

Energy Planner zařízení přímo neovládá, ale vytváří jednoduché signály pro vaše
automatizace:

- `binary_sensor.energy_planner_charge_now` pro povolení nabíjení ze sítě.
- `binary_sensor.energy_planner_discharge_allowed` pro povolení vybíjení.
- `sensor.energy_planner_unused_surplus_today` pro spuštění pružných spotřebičů,
  když je dost předpokládaného přebytku z FVE.
- Hodnotu každého `managed_<source>_suggested_tomorrow` jako vstup vlastní
  automatizace na další den; Energy Planner zařízení stále sám nespíná.
- Hodnotu EV `managed_<source>_suggested_today` jako solární rozpočet pro
  zbývající úplné plánovací sloty dneška.
- Režim `managed_<source>_charging_mode` EV plánu podle odjezdu jako vstup pro
  existující automatizaci Wallboxu. Volbu fáze, proudu a ochranu přetížení
  ponechte bezpečnostní logice Wallboxu.
- Per-load managed senzory pro prioritizaci spotřebičů, například nejdřív
  dohřát TUV a teprve potom povolit nabíjení EV.

Příklady automatizací s placeholdery jsou v
[příkladech automatizací](docs/automations.md). Automatizace vždy nejdřív ručně
otestujte ve vlastním Home Assistantu.

Plánování nabíjení ze sítě lze vypnout nezávisle v možnostech integrace. Po
vypnutí planner ignoruje okno plánovaného nabíjení,
`binary_sensor.energy_planner_charge_now` zůstane vypnutý a simulace plánu
nezahrne žádné nabíjení ze sítě.

## Ruční přepočet

Energy Planner se přepočítává automaticky v nastaveném intervalu, jehož výchozí
hodnota je 60 minut a který slouží k obnově předpovědi a jako bezpečnostní
záloha. Pro EV plán podle odjezdu navíc plánuje jednorázový přepočet na každý
začátek a konec plánovaného režimu, takže poradní přechody nečekají na periodický
interval. Změna EV požadavku energie, polohy, kabelu nebo povolení GRIDu vyvolá
přepočet po desetisekundovém debounce; změny SoC baterie a kumulativních zdrojů
energie si zachovávají 60sekundový debounce.

Deadline-aware EV akce používají povolovací okna s minimálním rozlišením 10
minut, zatímco podkladová SoC prognóza si zachovává nastavené jemnější
rozlišení. Pokud nastavený interval plánování není kompatibilní s 10 minutami,
Energy Planner použije nejmenší kompatibilní interval; například 15 minut vede
na 30minutové EV akční okno. Okno povoluje doporučený režim, ale nevyžaduje
maximální výkon nabíječky po celou dobu. Plánovaná energie proto může být nižší
než maximální kapacita okna a požadavek, který klesne na nulu, doporučení po
obnově vstupu ukončí dříve. Atributy entity `planned_until_departure` uvádějí
účinné rozlišení jako `action_window_minutes`.

Ruční přepočet spustíte přes **Developer Tools > Services**:

```text
energy_planner.recalculate
```

## Troubleshooting

- `insufficient_data` obvykle znamená, že povinná zdrojová entita chybí, je
  unavailable nebo není číselná.
- Pokud je spotřeba domu ve `W`, převeďte ji přes Integral helper na `kWh`.
- `warning` obvykle znamená, že nakonfigurovaný volitelný zdroj, například
  vybraná Solcast entita, chybí nebo nemá použitelnou předpověď.
- Nedostupné teplotní čidlo TUV zneplatní pouze doporučení daného zásobníku.
  Energy Planner u typu `hot_water` nikdy nepoužije jako náhradu historii
  spotřeby.
- Nedostupný požadavek energie EV nebo neplatný maximální výkon nabíječky
  zneplatní jen doporučení daného auta. Typ `electric_vehicle` nikdy nepoužije
  náhradní historii. `solar_only` GRID neplánuje; `deadline_aware` jej pouze
  vykazuje jako poradní rozhodnutí.
- Pokud jsou grafy prázdné, zkontrolujte v **Developer Tools > States**, že
  `sensor.energy_planner_soc_forecast` má atribut `points`.
- Pokud hodnoty po první instalaci vypadají zvláštně, počkejte alespoň 24 až 48
  hodin na historii.

Diagnostiku najdete na stránce integrace. Pomůže zkontrolovat nastavené entity,
aktivní možnosti, warnings a poslední výstup planneru.

## Odstranění

1. Otevřete **Nastavení > Zařízení a služby > Energy Planner**.
2. Smažte integrační položku.
3. Pokud jste instalovali přes HACS, odeberte Energy Planner i v HACS.
4. Restartujte Home Assistant, pokud si o to řekne.

Smazání integrační položky odstraní uloženou interní historii Energy Planneru.
Nesmaže vaše původní zdrojové entity, helpery, dashboardy ani automatizace.

## Další dokumentace

- [Detailní konfigurace](docs/configuration.md)
- [Všechny vytvořené entity](docs/entities.md)
- [Dashboard příklady](docs/dashboard.md)
- [Příklady automatizací](docs/automations.md)
- [Jak funguje historie](docs/history.md)
- [Detaily planneru](docs/planner.md)
